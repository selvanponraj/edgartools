import re
from dataclasses import dataclass, field
from typing import List, Dict, Set
from typing import Optional, Union, Any, Literal
from abc import ABC, abstractmethod
from bs4 import Tag, NavigableString
from prompt_toolkit.contrib.telnet.log import logger
from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderResult
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import textwrap
from edgar.files.html_documents import HtmlDocument, clean_html_root
from edgar.files.html_documents import DocumentData
from edgar.richtools import repr_rich

__all__ = ['SECHTMLParser', 'Document', 'DocumentNode', 'StyleInfo']



# Define unit types for type checking
UnitType = Literal['pt', 'px', 'in', 'cm', 'mm', '%']



@dataclass
class Width:
    """Represents a width value with its unit"""
    value: float
    unit: UnitType

    def to_chars(self, console_width: int) -> int:
        """Convert width to character count based on console width"""
        # Base conversion rates (at standard 80-char width)
        BASE_CONSOLE_WIDTH = 80  # standard width
        CHARS_PER_INCH = 12.3  # at standard width

        # Scale factor based on actual console width
        scale = console_width / BASE_CONSOLE_WIDTH

        # Convert to inches first
        inches = self._to_inches()

        # Convert to characters, scaling based on console width
        chars = round(inches * CHARS_PER_INCH * scale)

        # Handle percentage
        if self.unit == '%':
            return round(console_width * (self.value / 100))

        return min(chars, console_width)

    def _to_inches(self) -> float:
        """Convert any unit to inches"""
        conversions = {
            'in': 1.0,
            'pt': 1 / 72,  # 72 points per inch
            'px': 1 / 96,  # 96 pixels per inch
            'cm': 0.393701,  # 1 cm = 0.393701 inches
            'mm': 0.0393701,  # 1 mm = 0.0393701 inches
            '%': 1.0  # percentage handled separately in to_chars
        }
        return self.value * conversions[self.unit]


@dataclass
class StyleInfo:
    display: Optional[str] = None
    margin_top: Optional[float] = None
    margin_bottom: Optional[float] = None
    font_size: Optional[float] = None
    font_weight: Optional[str] = None
    text_align: Optional[str] = None
    line_height: Optional[float] = None
    width: Optional[Width] = None # Width in characters
    text_decoration: Optional[str] = None

    def merge(self, parent_style: Optional['StyleInfo']) -> 'StyleInfo':
        """Merge this style with parent style, child properties take precedence"""
        if not parent_style:
            return self

        # Create new style with parent values
        merged = StyleInfo(
            display=parent_style.display,
            margin_top=parent_style.margin_top,
            margin_bottom=parent_style.margin_bottom,
            font_size=parent_style.font_size,
            font_weight=parent_style.font_weight,
            text_align=parent_style.text_align,
            line_height=parent_style.line_height,
            width=parent_style.width,
            text_decoration=parent_style.text_decoration
        )

        # Override with child values where they exist
        if self.display is not None:
            merged.display = self.display
        if self.margin_top is not None:
            merged.margin_top = self.margin_top
        if self.margin_bottom is not None:
            merged.margin_bottom = self.margin_bottom
        if self.font_size is not None:
            merged.font_size = self.font_size
        if self.font_weight is not None:
            merged.font_weight = self.font_weight
        if self.text_align is not None:
            merged.text_align = self.text_align
        if self.line_height is not None:
            merged.line_height = self.line_height
        if self.width is not None:
            merged.width = self.width
        if self.text_decoration is not None:
            merged.text_decoration = self.text_decoration

        return merged

    def get_char_width(self, console_width: int = 80) -> Optional[int]:
        """Get width in characters, respecting console width"""
        if self.width is None:
            return None
        return min(self.width, console_width)


class BaseNode(ABC):

    """Abstract base class for all document nodes with metadata support"""
    metadata: Dict[str, Any] = field(default_factory=dict)

    """Abstract base class for all document nodes"""
    @abstractmethod
    def render(self, console_width: int) -> RenderResult:
        """Render the node for display"""
        pass

    @property
    @abstractmethod
    def type(self) -> str:
        """Return the type of the node"""
        pass

    def add_metadata(self, key: str, value: Any) -> None:
        """Add or update metadata"""
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata value with optional default"""
        return self.metadata.get(key, default)

    def remove_metadata(self, key: str) -> None:
        """Remove metadata if it exists"""
        self.metadata.pop(key, None)



@dataclass
class HeadingNode(BaseNode):
    content: str
    style: StyleInfo
    level: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return 'heading'

    def render(self, console_width: int) -> RenderResult:
        """Render heading with enhanced styling based on level"""
        # Enhanced style configurations based on heading level
        styles = {
            1: {
                "text_style": "bold cyan",
                "box": box.DOUBLE,
                "border_style": "cyan",
                "padding": (1, 2),
                "title": "§" if self.content else None  # Section symbol for level 1
            },
            2: {
                "text_style": "bold blue",
                "box": box.ROUNDED,
                "border_style": "blue",
                "padding": (1, 2),
                "title": "•" if self.content else None  # Bullet for level 2
            },
            3: {
                "text_style": "bold",
                "box": box.SIMPLE,
                "border_style": "white",
                "padding": (0, 2),
                "title": ">" if self.content else None  # Arrow for level 3
            },
            4: {
                "text_style": "dim bold",
                "box": box.MINIMAL,
                "border_style": "grey70",
                "padding": (0, 1),
                "title": "-" if self.content else None  # Dash for level 4
            }
        }

        # Get style configuration for current heading level, defaulting to level 4
        style_config = styles.get(self.level, styles[4])

        # Create base text with style
        text = Text(self.content.strip(), style=style_config["text_style"])

        # Apply text alignment based on style
        if self.style and self.style.text_align == 'center':
            text = Align.center(text)

        # Create panel with enhanced styling
        return Panel(
            text,
            box=style_config["box"],
            border_style=style_config["border_style"],
            padding=style_config["padding"],
            expand=True,
            title=style_config["title"],
            title_align="left"
        )


@dataclass
class TextBlockNode(BaseNode):
    content: str
    style: StyleInfo
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return 'text_block'

    def render(self, console_width: int) -> RenderResult:
        if not self.content:
            return Text("")

        width = console_width
        if self.style and self.style.width:
            width = min(self.style.width.to_chars(console_width), console_width)

        # Wrap text with improved handling
        def wrap_line(line: str) -> List[str]:
            if not line.strip():
                return ['']
            if len(line) <= width:
                return [line]

            wrapped = textwrap.wrap(
                line,
                width=width,
                break_long_words=True,
                break_on_hyphens=True,
                expand_tabs=True
            )

            # Handle orphaned words
            processed = []
            i = 0
            while i < len(wrapped):
                current_line = wrapped[i]
                if i < len(wrapped) - 1:
                    next_line = wrapped[i + 1]
                    if len(next_line) < width * 0.2 or ' ' not in next_line.strip():
                        combined = current_line + ' ' + next_line
                        if len(combined) <= width:
                            processed.append(combined)
                            i += 2
                            continue
                processed.append(current_line)
                i += 1
            return processed

        lines = self.content.splitlines(keepends=False)
        rendered_lines = []
        for line in lines:
            wrapped_lines = wrap_line(line.rstrip('\n'))
            rendered_lines.extend(wrapped_lines)
            if line.endswith('\n'):
                rendered_lines.append('')

        final_text = '\n'.join(rendered_lines)
        result = Text(final_text)

        if self.style:
            if self.style.text_align:
                align_map = {
                    'center': 'center',
                    'right': 'right',
                    'justify': 'full',
                    'left': 'left'
                }
                result.justify = align_map.get(self.style.text_align, 'left')

            if self.style.font_weight in ('bold', '700', '800', '900'):
                result.stylize("bold")

        return result



@dataclass
class TableCell:
    content: str
    colspan: int = 1
    rowspan: int = 1
    align: str = 'left'
    is_currency: bool = False


@dataclass
class TableRow:
    cells: List[TableCell]
    is_header: bool = False

    @property
    def virtual_columns(self):
        return sum(cell.colspan for cell in self.cells)


@dataclass
class TableNode(BaseNode):
    content: List[TableRow]
    style: StyleInfo
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return 'table'

    def render(self, console_width: int) -> RenderResult:
        from edgar.files.tables import TableProcessor
        processed_table = TableProcessor.process_table(self)
        if not processed_table:
            return None

        table = Table(
            box=box.SIMPLE,
            border_style="blue",
            padding=(0, 1),
            show_header=bool(processed_table.headers),
            row_styles=["", "gray54"],
            collapse_padding=True,
            width=None
        )

        # Add columns
        for col_idx, alignment in enumerate(processed_table.column_alignments):
            table.add_column(
                header=processed_table.headers[col_idx] if processed_table.headers else None,
                justify=alignment,
                vertical="middle"
            )

        # Add data rows
        for row in processed_table.data_rows:
            table.add_row(*row)

        return table


def create_node(
        type_: str,
        content: Union[str, List[TableRow]],
        style: StyleInfo,
        level: int = 1,
        metadata: Optional[Dict[str, Any]] = None
) -> BaseNode:
    """Create a node with optional metadata"""
    metadata = metadata or {}

    if type_ == 'heading':
        return HeadingNode(content=content, style=style, level=level, metadata=metadata)
    elif type_ == 'text_block':
        return TextBlockNode(content=content, style=style, metadata=metadata)
    elif type_ == 'table':
        return TableNode(content=content, style=style, metadata=metadata)
    else:
        raise ValueError(f"Unknown node type: {type_}")


# 1. Add type literals and type guards
NodeType = Literal['heading', 'text_block', 'table']
ContentType = Union[str, Dict[str, Any], List[TableRow]]

def is_table_content(content: ContentType) -> bool:
    return isinstance(content, list) and all(isinstance(x, TableRow) for x in content)

def is_text_content(content: ContentType) -> bool:
    return isinstance(content, str)

def is_dict_content(content: ContentType) -> bool:
    return isinstance(content, dict)

@dataclass
class DocumentNode:
    type: Literal['heading', 'text_block', 'table']  # Changed from 'paragraph' to 'text_block'
    content: Union[str, Dict[str, Any], List[TableRow]]
    style: StyleInfo
    level: int = 0

    def _validate_content(self) -> None:
        """Validate content matches the node type"""
        if self.type == 'table' and not is_table_content(self.content):
            raise ValueError(f"Table node must have List[TableRow] content, got {type(self.content)}")
        elif self.type in ('heading', 'text_block') and not is_text_content(self.content):
            raise ValueError(f"{self.type} node must have string content, got {type(self.content)}")

    @property
    def text(self) -> str:
        """Helper method for accessing text content"""
        if not is_text_content(self.content):
            raise ValueError(f"Cannot get text from {self.type} node")
        return self.content

    @property
    def rows(self) -> List[TableRow]:
        """Helper method for accessing table rows"""
        if not is_table_content(self.content):
            raise ValueError(f"Cannot get rows from {self.type} node")
        return self.content



@dataclass
class Document:
    """Document class that works with the new node hierarchy"""
    nodes: List[BaseNode]

    def __len__(self):
        return len(self.nodes)

    def __getitem__(self, index):
        return self.nodes[index]

    def empty(self) -> bool:
        return len(self.nodes) == 0

    @staticmethod
    def _get_width() -> int:
        """Get the width of the console that this document is being rendered into"""
        return Console().width

    @property
    def tables(self) -> List[BaseNode]:
        """Get all table nodes in the document"""
        return [node for node in self.nodes if node.type == 'table']

    @classmethod
    def parse(cls, html: str) -> Optional['Document']:
        root = HtmlDocument.get_root(html)
        if root:
            parser = SECHTMLParser(root)
            return parser.parse()

    def to_markdown(self) -> str:
        from edgar.files.markdown import MarkdownRenderer
        return MarkdownRenderer(self).render()

    def __rich__(self) -> RenderResult:
        """Rich console protocol for rendering document"""
        console = Console()
        console_width = console.width

        renderable_elements = []
        for node in self.nodes:
            element = node.render(console_width)
            if element:
                renderable_elements.append(element)

        return Group(*renderable_elements)

    def __repr__(self):
        return repr_rich(self)


@dataclass
class StyledText:
    """Represents a piece of text with its associated style"""
    content: str
    style: StyleInfo
    is_paragraph: bool = False  # Track if this came from a <p> tag


class SECHTMLParser:
    def __init__(self, root: Tag, extract_data: bool = True):
        self.data:DocumentData = HtmlDocument.extract_data(root) if extract_data else None
        self.root:Tag = clean_html_root(root)
        self.base_font_size = 10.0  # Default base font size in pt
        self.style_stack: List[StyleInfo] = []

    def parse(self) -> Optional[Document]:
        body = self.root.find('body')
        if not body:
            logger.warn("No body tag found in HTML")
            return None

        nodes = self._parse_element(body)
        return Document(nodes=nodes)

    def _parse_element(self, element: Tag) -> List[BaseNode]:
        nodes = []

        for child in element.children:
            if not isinstance(child, Tag):
                continue

            node = self._process_element(child)
            if node:
                nodes.extend(node if isinstance(node, list) else [node])

        return self._merge_adjacent_nodes(nodes)

    def parse_style(self, style_str: str) -> StyleInfo:
        """Parse inline CSS style string into StyleInfo object"""
        style = StyleInfo()
        if not style_str:
            return style

        # Split style string into individual properties
        properties = [p.strip() for p in style_str.split(';') if p.strip()]
        for prop in properties:
            if ':' not in prop:
                continue

            key, value = prop.split(':', 1)
            key = key.strip().lower()
            value = value.strip().lower()

            # Parse different style properties
            if key == 'width':
                width = self._parse_width(value)
                if width:
                    style.width = width
            elif key == 'display':
                style.display = value
            elif key == 'margin-top':
                style.margin_top = self._parse_unit(value)
            elif key == 'margin-bottom':
                style.margin_bottom = self._parse_unit(value)
            elif key == 'font-size':
                style.font_size = self._parse_unit(value)
            elif key == 'font-weight':
                style.font_weight = value
            elif key == 'text-align':
                style.text_align = value
            elif key == 'line-height':
                style.line_height = self._parse_unit(value)
            elif key == 'text-decoration':
                style.text_decoration = value

        return style

    def _parse_width(self, value: str) -> Optional[Width]:
        """Parse CSS width value into Width object"""
        if not value:
            return None

        # Handle percentage values
        if value.endswith('%'):
            try:
                return Width(float(value[:-1]), '%')
            except ValueError:
                return None

        # Extract number and unit
        match = re.match(r'(-?\d*\.?\d+)([a-z]*)', value)
        if not match:
            return None

        number, unit = match.groups()
        try:
            number = float(number)
        except ValueError:
            return None

        # Map CSS units to our unit types
        unit_map = {
            'in': 'in',
            'pt': 'pt',
            'px': 'px',
            'cm': 'cm',
            'mm': 'mm',
            '': 'px'  # default to pixels if no unit specified
        }

        unit = unit_map.get(unit)
        if not unit:
            return None

        return Width(number, unit)


    def _parse_unit(self, value: str) -> Optional[float]:
        """Parse CSS unit values into integer character width"""
        if not value:
            return None

        # Handle percentage values
        if value.endswith('%'):
            try:
                return float(value[:-1]) / 100.0
            except ValueError:
                return None

        # Extract number and unit
        match = re.match(r'(-?\d*\.?\d+)([a-z]*)', value)
        if not match:
            return None

        number, unit = match.groups()
        try:
            number = float(number)
        except ValueError:
            return None

        # Convert different units to characters
        # Assuming typical terminal character widths:
        # - 80 chars ≈ 6.5 inches
        # - 1 inch ≈ 12.3 chars
        chars_per_unit = {
            'in': 12.3,     # 1 inch ≈ 12.3 chars
            'pt': 12.3/72,  # 1 pt = 1/72 inch
            'px': 12.3/96,  # 1 px = 1/96 inch
            'cm': 4.84,     # 1 cm ≈ 4.84 chars
            'mm': 0.484,    # 1 mm ≈ 0.484 chars
            'em': 1.6,      # 1 em ≈ 1.6 chars (assuming typical font)
            'rem': 1.6,     # Same as em
        }

        multiplier = chars_per_unit.get(unit, 1.0)
        return int(number * multiplier)


    def _clean_text(self, text: str) -> str:
        """Clean and normalize text content while preserving meaningful whitespace"""
        # Replace HTML entities
        entities = {
            '&nbsp;': ' ',
            '&amp;': '&',
            '&lt;': '<',
            '&gt;': '>',
            '&quot;': '"',
            '&apos;': "'",
            '&#8202;': ' ',  # hair space
            '&#8203;': ''  # zero-width space
        }

        for entity, replacement in entities.items():
            text = text.replace(entity, replacement)

        # Normalize whitespace while preserving single newlines
        lines = text.splitlines()
        lines = [' '.join(line.split()) for line in lines]
        text = '\n'.join(lines)

        return text

    def _looks_like_header(self, element: Tag, style: StyleInfo) -> bool:
        """Determine if a div looks like it should be treated as a heading"""
        # Don't treat divs with spans as headers unless they have very clear heading characteristics
        if element.find('span'):
            return False

        # Get text content
        text = element.get_text(strip=True)
        if not text:
            return False

        # More strict header characteristics
        hints = [
            bool(style.font_weight and style.font_weight in ['bold', '700', '800', '900']),  # Bold text
            bool(style.margin_top and style.margin_top > 18),  # Significant top margin
            bool(len(text.split()) <= 8),  # Very short text (reduced from 10)
            not bool(element.find('table')),  # No tables inside
            not any(c.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p'] for c in element.find_all()),
            # No header or paragraph tags inside
            bool(style.font_size and style.font_size >= 1.2 * self.base_font_size)  # Notably larger font
        ]

        # More strict requirements: need more positive hints
        return sum(hints) >= 4 and hints[0]  # Must be bold plus at least 3 other hints

    def _determine_heading_level(self, style: StyleInfo) -> int:
        """Determine heading level based on styling"""
        if not style:
            return 2  # Default level

        # Use font size relative to base size to determine level
        if style.font_size:
            size_ratio = style.font_size / self.base_font_size
            if size_ratio >= 1.8:  # Much larger
                return 1
            elif size_ratio >= 1.4:  # Notably larger
                return 2
            elif size_ratio >= 1.2:  # Somewhat larger
                return 3

        # If bold but not significantly larger, treat as lower-level heading
        if style.font_weight in ['bold', '700', '800', '900']:
            return 3

        return 4  # Default to lowest level if uncertain

    def _process_element(self, element: Tag) -> Optional[Union[BaseNode, List[BaseNode]]]:
        """Process an element into one or more nodes with inherited styles"""
        # Phase 1: Mark all ancestors of tables
        tables = element.find_all('table', recursive=True)
        for table in tables:
            parent = table.parent
            while parent:
                parent['has_table'] = True
                parent = parent.parent

        # Parse current element's style
        current_style = self.parse_style(element.get('style', ''))

        # Merge with parent style if there is one
        if self.style_stack:
            current_style = current_style.merge(self.style_stack[-1])

        # Push current style to stack before processing children
        self.style_stack.append(current_style)

        try:
            # Handle ix: tags by processing their content sequentially
            if element.name.startswith('ix:'):
                nodes = []
                children = list(element.children)  # Convert to list to avoid iterator modification

                for i, child in enumerate(children):
                    if isinstance(child, Tag):
                        if child.name == 'table':
                            # Process table
                            table_node = self._process_table(child)
                            if table_node:
                                nodes.append(table_node)
                        elif child.name == 'p':
                            # Process paragraph
                            para_node = self._process_paragraph(child, current_style)
                            if para_node:
                                nodes.append(para_node)
                        elif child.name == 'div':
                            # Process div with its own style
                            div_style = self.parse_style(child.get('style', '')).merge(current_style)
                            div_result = self._process_structured_content(child, div_style)
                            if div_result:
                                if isinstance(div_result, list):
                                    nodes.extend(div_result)
                                else:
                                    nodes.append(div_result)
                        else:
                            # Process other elements recursively
                            child_result = self._process_element(child)
                            if child_result:
                                if isinstance(child_result, list):
                                    nodes.extend(child_result)
                                else:
                                    nodes.append(child_result)

                # Return the collected nodes
                return nodes[0] if len(nodes) == 1 else nodes if nodes else None

            # Process table elements directly
            if element.name == 'table':
                return self._process_table(element)

            elif element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(element.name[1])
                return create_node(
                    type_='heading',
                    content=element.get_text(strip=True),
                    style=current_style,
                    level=level
                )

            elif element.name == 'p':
                return self._process_paragraph(element, current_style)

            elif element.name == 'div':
                # Phase 2: Process content based on whether this div contains tables
                if element.get('has_table'):
                    # Structure-preserving mode for divs with tables
                    return self._process_structured_content(element, current_style)
                else:
                    # Content-combining mode for divs without tables
                    return self._process_inline_content(element, current_style)

            # For other elements, process children
            nodes = []
            for child in element.children:
                if isinstance(child, Tag):
                    child_result = self._process_element(child)
                    if child_result:
                        if isinstance(child_result, list):
                            nodes.extend(child_result)
                        else:
                            nodes.append(child_result)

            return nodes[0] if len(nodes) == 1 else nodes if nodes else None

        finally:
            # Always pop the style from stack when done with this element
            self.style_stack.pop()

    def _process_structured_content(self, element: Tag, style: StyleInfo) -> Optional[Union[BaseNode, List[BaseNode]]]:
        """Process content in structure-preserving mode (for elements containing tables)"""
        nodes = []
        text_parts = []

        def flush_text():
            if text_parts:
                text = ' '.join(text_parts).strip()
                if text:
                    nodes.append(create_node(
                        type_='text_block',
                        content=text,
                        style=style
                    ))
                text_parts.clear()

        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    text_parts.append(text)
            elif isinstance(child, Tag):
                if child.name == 'table':
                    flush_text()
                    table_node = self._process_table(child)
                    if table_node:
                        nodes.append(table_node)
                elif child.get('has_table'):
                    # This child contains a table somewhere, process structurally
                    flush_text()
                    child_result = self._process_element(child)
                    if child_result:
                        if isinstance(child_result, list):
                            nodes.extend(child_result)
                        else:
                            nodes.append(child_result)
                else:
                    # Non-table-containing element, can process for text
                    text = self._get_text_with_spacing(child).strip()
                    if text:
                        text_parts.append(text)

        flush_text()
        return nodes[0] if len(nodes) == 1 else nodes if nodes else None

    def _process_inline_content(self, element: Tag, style: StyleInfo) -> Optional[Union[BaseNode, List[BaseNode]]]:
        """Process content in content-combining mode (for elements without tables)"""
        nodes = []
        text_parts = []

        def flush_text():
            if text_parts:
                text = ' '.join(text_parts).strip()
                if text:
                    nodes.append(create_node(
                        type_='text_block',
                        content=text,
                        style=style
                    ))
                text_parts.clear()

        # Process children while handling special cases
        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text and text != '​':  # Skip zero-width spaces
                    text_parts.append(text)
            elif isinstance(child, Tag):
                if child.name == 'br':
                    text_parts.append('\n')
                elif child.name == 'p':
                    # Flush any current text before handling paragraph
                    flush_text()
                    # Process paragraph content
                    para_style = self.parse_style(child.get('style', '')).merge(style)
                    para_result = self._process_paragraph(child, para_style)
                    if para_result:
                        nodes.append(para_result)
                        # Add newline after paragraph if there isn't one
                        if text_parts and text_parts[-1] != '\n':
                            text_parts.append('\n')
                elif child.name == 'font':
                    # Process font tag content
                    text = self._get_text_with_spacing(child).strip()
                    if text:
                        text_parts.append(text)
                elif child.name == 'div':
                    # Check for bullet point structure
                    float_style = self.parse_style(child.get('style', '')).display
                    if float_style == 'float:left':
                        # This is a bullet point marker
                        bullet_text = child.get_text().strip()
                        if bullet_text:
                            text_parts.append(bullet_text + ' ')
                    elif 'clear:both' in child.get('style', ''):
                        # This is a bullet point separator
                        if text_parts and text_parts[-1] != '\n':
                            text_parts.append('\n')
                    else:
                        # Regular div - process its content
                        inner_result = self._process_inline_content(child, style)
                        if inner_result:
                            # Flush any current text before adding the new content
                            flush_text()
                            if isinstance(inner_result, list):
                                nodes.extend(inner_result)
                            else:
                                nodes.append(inner_result)
                elif not self._is_block_element(child):
                    text = self._get_text_with_spacing(child).strip()
                    if text:
                        text_parts.append(text)

        # Flush any remaining text
        flush_text()

        # Return appropriate result based on what we collected
        if len(nodes) == 1:
            return nodes[0]
        elif len(nodes) > 1:
            return nodes
        elif len(text_parts) > 0:
            text = ' '.join(text_parts).strip()
            if text:
                return create_node(
                    type_='text_block',
                    content=text,
                    style=style
                )
        return None



    def _normalize_text_parts(self, parts: List[str]) -> str:
        """Normalize text parts while preserving intentional line breaks"""
        # Remove empty parts and normalize spaces
        normalized_parts = []
        for i, part in enumerate(parts):
            if part == '\n':
                # Keep newlines but ensure no extra spaces around them
                normalized_parts.append('\n')
            else:
                # For text content, strip and add only if non-empty
                stripped = part.strip()
                if stripped:
                    # Don't add space if previous part was a newline or this is the first part
                    if normalized_parts and normalized_parts[-1] != '\n' and i > 0:
                        normalized_parts.append(' ')
                    normalized_parts.append(stripped)

        # Join all parts and remove any extra whitespace around newlines
        text = ''.join(normalized_parts)

        # Clean up any potential multiple newlines or spaces
        #text = re.sub(r'\s*\n\s*', '\n', text)
        text = re.sub(r' +', ' ', text)

        return text.strip()

    def _process_table(self, element: Tag) -> Optional[BaseNode]:
        """Process table element into a TableNode with precise line break handling"""
        if not element:
            return None

        def replace_html_entities(text: str) -> str:
            """Replace HTML entities with markdown-safe alternatives"""
            # Map of HTML entities to their markdown-safe replacements
            entity_replacements = {
                '&horbar;': '-----',  # Horizontal bar
                '&mdash;': '-----',  # Em dash
                '&ndash;': '---',  # En dash
                '&minus;': '-',  # Minus sign
                '&hyphen;': '-',  # Hyphen
                '&dash;': '-',  # Generic dash
                # Add other common entities that might need replacement
                '&nbsp;': ' ',  # Non-breaking space
                '&amp;': '&',  # Ampersand
                '&lt;': '<',  # Less than
                '&gt;': '>',  # Greater than
                '&quot;': '"',  # Quote
                '&apos;': "'",  # Apostrophe
                '&#8202;': ' ',  # Hair space
                '&#8203;': '',  # Zero-width space
                '&#x2014;': '-----',  # Another way to encode mdash
                '&#x2013;': '---',  # Another way to encode ndash
                '&#x2212;': '-',  # Another way to encode minus
            }

            # Also handle numeric entities that might represent dashes
            # Unicode values for various dashes
            dash_codepoints = {
                '8208': '-',  # hyphen
                '8209': '-',  # non-breaking hyphen
                '8210': '-',  # figure dash
                '8211': '---',  # en dash
                '8212': '-----',  # em dash
                '8213': '-----',  # horizontal bar
                '8722': '-',  # minus sign
            }

            result = text
            # Replace named entities
            for entity, replacement in entity_replacements.items():
                result = result.replace(entity, replacement)

            # Replace numeric entities (both decimal and hex) for dashes
            for code, replacement in dash_codepoints.items():
                # Replace decimal format
                result = result.replace(f'&#{code};', replacement)
                # Replace hexadecimal format
                result = result.replace(f'&#x{hex(int(code))[2:]};', replacement)

            return result

        def extract_cell_text(cell: Tag) -> str:
            """Extract text from cell with careful line break handling"""
            # First check for div children
            divs = cell.find_all('div', recursive=False)
            if divs:
                # Get text from each div and handle entities
                div_texts = [replace_html_entities(div.get_text(strip=True)) for div in divs]
                return '\n'.join(div_texts)

            # Handle <br/> tags by replacing them with newlines
            for br in cell.find_all('br'):
                br.replace_with('\n')

            # Get text and handle entities
            text = cell.get_text(strip=False)
            text = replace_html_entities(text)
            return text.strip()

        def process_cell(cell: Tag) -> List[TableCell]:
            """Process cell preserving exact colspan and positioning values correctly"""
            colspan = int(cell.get('colspan', '1'))
            style = self.parse_style(cell.get('style', ''))

            text = extract_cell_text(cell)

            # If this is a right-aligned cell with colspan > 1 (like percentage values)
            if style.text_align == 'right' and colspan > 1:
                # Create empty cells for all but last column of colspan
                cells = [
                    TableCell(content='', colspan=1, align='right', is_currency=False)
                    for _ in range(colspan - 1)
                ]
                # Add actual value in last column
                cells.append(TableCell(
                    content=text,
                    colspan=1,
                    align='right',
                    is_currency=False
                ))
                return cells

            # For single cells
            return [TableCell(
                content=text,
                colspan=colspan,
                align=style.text_align or 'left',
                is_currency=text.startswith('$')
            )]


        def process_row(row: Tag) -> TableRow:
            """Process row preserving cell structure"""
            cells = []
            for td in row.find_all(['td', 'th']):
                cells.extend(process_cell(td))

            return TableRow(cells=cells, is_header=row.find_parent('thead') is not None)

        # Process all rows
        rows = []
        for tr in element.find_all('tr'):
            row = process_row(tr)
            if row.cells:
                rows.append(row)

        if rows:
            # Create metadata from table attributes
            metadata = {
                'id': element.get('id', ''),
                'class': element.get('class', []),
                'data_attrs': {
                    k: v for k, v in element.attrs.items()
                    if k.startswith('data-')
                }
            }

            return create_node(
                'table',
                rows,
                self.parse_style(element.get('style', '')),
                metadata=metadata
            )

        return None

    def _process_paragraph(self, element: Tag, style: StyleInfo) -> Optional[BaseNode]:
        """Process a paragraph element with inherited styles"""
        text_parts = []
        last_was_text = False

        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip():
                    text_parts.append(text)
                    last_was_text = True
                elif text.isspace() and last_was_text:
                    text_parts.append(' ')
            elif isinstance(child, Tag):
                if child.name == 'br':
                    text_parts.append('\n')
                    last_was_text = False
                elif child.name in ['span', 'font', 'strong', 'em', 'b', 'i', 'a']:
                    text = self._get_text_with_spacing(child)
                    if text.strip():
                        text_parts.append(text.strip())
                        last_was_text = True

        if not text_parts:
            return None

        # Join all parts and normalize whitespace while preserving intentional breaks
        text = ''.join(text_parts)
        # Split into lines, normalize each line's whitespace, then rejoin
        lines = [' '.join(line.split()) for line in text.split('\n')]
        text = '\n'.join(line for line in lines if line)

        if text.strip():
            return create_node(
                type_='text_block',
                content=text,
                style=style
            )

        return None

    def _normalize_text(self, pieces: List[StyledText], is_paragraph: bool) -> str:
        """Normalize text differently for paragraphs vs general text blocks"""
        if is_paragraph:
            # For actual paragraphs, collapse all whitespace
            text = ' '.join(piece.content for piece in pieces)
            return ' '.join(text.split())
        else:
            # For general text blocks, preserve line breaks
            lines = []
            current_line = []

            for piece in pieces:
                if piece.content == '\n':
                    # Flush current line
                    if current_line:
                        lines.append(' '.join(''.join(current_line).split()))
                        current_line = []
                    lines.append('')  # Add empty line for break
                else:
                    current_line.append(piece.content)

            # Flush any remaining content
            if current_line:
                lines.append(' '.join(''.join(current_line).split()))

            # Remove any extra empty lines but preserve single line breaks
            text = '\n'.join(lines)
            return re.sub(r'\n{3,}', '\n\n', text)

    def _is_block_element(self, element: Tag) -> bool:
        """Determine if an element is block-level"""
        # Check explicit display style first
        style = self.parse_style(element.get('style', ''))
        if style.display:
            return style.display != 'inline'

        # Default block elements
        block_elements = {
            'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li', 'blockquote', 'pre', 'hr',
            'table', 'form', 'fieldset', 'address'
        }

        return element.name in block_elements and 'float:left' not in element.get('style', '')


    def _collect_styled_text(self, element: Tag, style: StyleInfo) -> List[StyledText]:
        """Collect text with style information from inline elements"""
        pieces = []

        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip():
                    pieces.append(StyledText(text, style))
            elif isinstance(child, Tag):
                if child.name == 'br':
                    pieces.append(StyledText('\n', style))
                elif child.name != 'table':  # Skip tables in inline collection
                    child_style = self._get_combined_style(child, style)
                    pieces.extend(self._collect_styled_text(child, child_style))

        return pieces

    def _get_combined_style(self, element: Tag, parent_style: StyleInfo) -> StyleInfo:
        """Combine element's style with parent style, including HTML attributes"""
        style = self.parse_style(element.get('style', ''))

        # Handle specific HTML tags and their attributes
        if element.name == 'font':
            if size := element.get('size'):
                try:
                    size_num = float(size.replace('pt', ''))
                    style.font_size = size_num
                except ValueError:
                    pass

        elif element.name in {'b', 'strong'}:
            style.font_weight = 'bold'
        elif element.name in {'i', 'em'}:
            style.font_style = 'italic'

        return style.merge(parent_style)

    def _convert_pieces_to_nodes(self, pieces: List[StyledText]) -> List[DocumentNode]:
        """Convert collected text pieces into document nodes"""
        nodes = []
        current_paragraph: List[StyledText] = []

        def flush_paragraph():
            if not current_paragraph:
                return

            # Combine text and determine final style
            text = self._normalize_paragraph_text(current_paragraph)
            # Use the most specific (last) style for the paragraph
            final_style = current_paragraph[-1].style

            if text.strip():
                nodes.append(DocumentNode(
                    type='text_block',
                    content=text,
                    style=final_style
                ))
            current_paragraph.clear()

        for piece in pieces:
            if piece.is_block:
                flush_paragraph()
            else:
                current_paragraph.append(piece)

        # Flush any remaining content
        flush_paragraph()

        return nodes

    def _normalize_paragraph_text(self, pieces: List[StyledText]) -> str:
        """Normalize text within a paragraph while preserving intentional breaks"""
        # Join all pieces and split into lines
        text = ''.join(piece.content for piece in pieces)
        lines = text.splitlines()

        # Normalize each line individually
        normalized_lines = []
        for line in lines:
            # Collapse whitespace within each line
            normalized = ' '.join(line.split())
            if normalized:
                normalized_lines.append(normalized)

        # Join lines with single newlines
        return '\n'.join(normalized_lines)

    def _is_inline(self, element: Tag) -> bool:
        """Determine if an element should be treated as inline"""
        style = self.parse_style(element.get('style', ''))
        if style.display == 'inline':
            return True

        # Standard inline elements
        inline_elements = {
            'span', 'font', 'b', 'strong', 'i', 'em', 'a',
            'sub', 'sup', 'u', 'small', 'mark'
        }

        return element.name in inline_elements

    def _is_empty_text(self, text: str) -> bool:
        """Check if text is effectively empty"""
        return not bool(text.strip())

    def _get_text_with_spacing(self, element: Tag) -> str:
        """Extract text while preserving meaningful whitespace"""
        if element.name == 'table':
            return ''

        texts = []
        last_was_text = False

        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip():
                    texts.append(text.strip())
                    last_was_text = True
                elif text.isspace() and last_was_text:
                    texts.append(' ')
            elif child.name == 'br':
                texts.append('\n')
                last_was_text = False
            elif child.name == 'table':
                continue
            else:
                child_text = self._get_text_with_spacing(child)
                if child_text.strip():
                    # Only add space if needed
                    if texts and last_was_text and not texts[-1].endswith(' ') and not child_text.startswith(' '):
                        texts.append(' ')
                    texts.append(child_text.strip())
                    last_was_text = True

        return ''.join(texts)

    def _merge_adjacent_nodes(self, nodes: List[BaseNode]) -> List[BaseNode]:
        """Merge adjacent nodes while preserving styling from both nodes"""
        if not nodes:
            return []

        def merge_styles(style1: StyleInfo, style2: StyleInfo) -> StyleInfo:
            """Merge two styles intelligently"""
            # Start with a new style object
            merged = StyleInfo()

            # For each style attribute, take the non-None value
            # If both have values, use the more specific one
            merged.display = style2.display or style1.display
            merged.margin_top = style1.margin_top  # Keep first node's top margin
            merged.margin_bottom = style2.margin_bottom  # Keep second node's bottom margin

            # For font properties, prefer the second node's style if it's different
            # This preserves intentional style changes in the second block
            if style2.font_size and style2.font_size != style1.font_size:
                merged.font_size = style2.font_size
            else:
                merged.font_size = style1.font_size

            if style2.font_weight and style2.font_weight != style1.font_weight:
                merged.font_weight = style2.font_weight
            else:
                merged.font_weight = style1.font_weight

            # For alignment, if they differ, don't merge
            if style1.text_align != style2.text_align:
                return None
            merged.text_align = style1.text_align

            # Improved width handling
            if style1.width and style2.width:
                # If units differ, prefer the larger width's unit
                if style1.width.unit != style2.width.unit:
                    # Convert both to pixels for comparison
                    # This is a simplified conversion - you might want to use the existing
                    # Width.to_chars method for more accurate conversion
                    w1_px = _to_pixels(style1.width)
                    w2_px = _to_pixels(style2.width)

                    # If one width is significantly smaller (like a bullet point)
                    # use the larger width
                    if w1_px < w2_px * 0.3:  # First node is much smaller
                        merged.width = style2.width
                    elif w2_px < w1_px * 0.3:  # Second node is much smaller
                        merged.width = style1.width
                    else:
                        # Widths are comparable, use the second node's width
                        merged.width = style2.width
                else:
                    # Same units, apply the same logic
                    if style1.width.value < style2.width.value * 0.3:
                        merged.width = style2.width
                    elif style2.width.value < style1.width.value * 0.3:
                        merged.width = style1.width
                    else:
                        merged.width = style2.width
            else:
                # If only one has width, use that
                merged.width = style2.width or style1.width

            merged.text_decoration = style2.text_decoration or style1.text_decoration
            merged.line_height = style2.line_height or style1.line_height

            return merged

        def _to_pixels(width: Width) -> float:
            """Convert width to pixels for comparison"""
            # Conversion factors (approximate)
            conversions = {
                'px': 1,
                'pt': 1.333,  # 1pt ≈ 1.333px
                'in': 96,  # 1in = 96px
                'cm': 37.795,  # 1cm ≈ 37.795px
                'mm': 3.7795,  # 1mm ≈ 3.7795px
                '%': 1  # Handle percentages separately
            }
            return width.value * conversions.get(width.unit, 1)

        def can_merge_nodes(node1: BaseNode, node2: BaseNode) -> bool:
            """Determine if two nodes can be safely merged"""
            if node1.type != 'text_block' or node2.type != 'text_block':
                return False

            # Don't merge if either has special metadata
            if node1.metadata or node2.metadata:
                return False

            # Try to merge styles
            merged_style = merge_styles(node1.style, node2.style)
            if merged_style is None:
                return False

            return True

        merged = []
        current = None

        for node in nodes:
            if not current:
                current = node
                continue

            if can_merge_nodes(current, node):
                merged_style = merge_styles(current.style, node.style)
                # Create new merged text block with the combined style
                merged_content = f"{current.content}\n\n{node.content}"
                current = create_node(
                    'text_block',
                    merged_content,
                    merged_style
                )
            else:
                merged.append(current)
                current = node

        if current:
            merged.append(current)

        return merged



    def _is_heading(self, element: Tag, style: StyleInfo) -> bool:
        # Heuristics for heading detection
        if not style:
            return False

        # Check font size
        is_larger = (style.font_size or 0) > self.base_font_size

        # Check font weight
        is_bold = style.font_weight in ['bold', '700', '800', '900']

        # Check content length
        text = element.get_text(strip=True)
        is_short = len(text) < 200  # Arbitrary threshold

        # Combined heuristics
        return (is_larger or is_bold) and is_short



    def _similar_styles(self, style1: StyleInfo, style2: StyleInfo) -> bool:
        # Compare relevant style attributes to determine if they're similar
        return (
                style1.font_size == style2.font_size and
                style1.font_weight == style2.font_weight and
                style1.text_align == style2.text_align
        )




