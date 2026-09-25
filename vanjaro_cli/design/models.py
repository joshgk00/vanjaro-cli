"""Versioned, source-neutral models for Design Document v1 artifacts.

Design Document models deliberately reject unknown fields. Forward-compatible
data belongs in an explicit ``metadata`` or ``raw`` mapping until a new schema
version promotes it into the public contract.
"""

from __future__ import annotations

from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = [
    "Alignment",
    "AssetKind",
    "AssetRecord",
    "AssetRole",
    "BoundingBox",
    "BreakpointName",
    "CandidateRole",
    "ConditionBound",
    "ContentElement",
    "ContentKind",
    "DecorativeLayer",
    "DesignAnalysis",
    "DesignDocument",
    "DesignSource",
    "DesignTokens",
    "DesignWarning",
    "EvidenceStatus",
    "Interaction",
    "InteractionKind",
    "LayoutKind",
    "LayoutObservation",
    "LayoutRegion",
    "MediaPosition",
    "NavigationVisibility",
    "ObservationMethod",
    "Page",
    "Provenance",
    "RepeatGroup",
    "RepeatGroupItem",
    "RepeatGroupKind",
    "ResponsiveCondition",
    "ResponsiveConditionKind",
    "ResponsiveConditionStatus",
    "ResponsiveObservation",
    "Section",
    "SeoMetadata",
    "SourceKind",
    "StyleObservation",
    "StyleProperty",
    "StyleSet",
    "TokenValue",
    "TypographyToken",
    "Viewport",
    "WarningSeverity",
]


class _DesignModel(BaseModel):
    """Strict base model used by every public Design Document structure."""

    model_config = ConfigDict(extra="forbid")


class SourceKind(str, Enum):
    """Supported origins for a Design Document."""

    LIVE_HTML = "live_html"
    FIGMA = "figma"
    IMAGE = "image"
    LEGACY_SECTIONS = "legacy_sections"
    COMPOSITE = "composite"


class BreakpointName(str, Enum):
    """Canonical responsive breakpoint names."""

    DESKTOP = "desktop"
    TABLET = "tablet"
    MOBILE = "mobile"


class EvidenceStatus(str, Enum):
    """Whether evidence was directly observed or inferred."""

    OBSERVED = "observed"
    INFERRED = "inferred"


class ResponsiveConditionKind(str, Enum):
    """A supported bounded width comparison for a responsive condition."""

    MIN_WIDTH = "min_width"
    MAX_WIDTH = "max_width"


class ResponsiveConditionStatus(str, Enum):
    """Whether a responsive condition's winning-rule attribution is proven.

    ``OBSERVED`` means a media-conditioned declaration was proven to win the
    cascade among every declaration whose bounds are satisfied at the
    sampled viewport, and its value matches the sampled computed value.
    ``UNRESOLVED`` means evidence was gathered but correct attribution could
    not be proved (an unsupported media/container expression could win the
    cascade, no declaration's condition is satisfied at the sampled width,
    or the winning declaration's value does not match the sample) -- this is
    an explicit, actionable gap, never a fabricated authored breakpoint.
    """

    OBSERVED = "observed"
    UNRESOLVED = "unresolved"


class ObservationMethod(str, Enum):
    """Mechanism that produced a provenance record."""

    STATIC = "static"
    RENDERED = "rendered"
    API = "api"
    INFERRED = "inferred"
    LEGACY = "legacy"
    MANUAL = "manual"


class ContentKind(str, Enum):
    """Visitor-facing element kinds defined by Design Document v1."""

    HEADING = "heading"
    TEXT = "text"
    IMAGE = "image"
    BUTTON = "button"
    LINK = "link"
    LIST = "list"
    LIST_ITEM = "list_item"
    QUOTE = "quote"
    STAT = "stat"
    VIDEO = "video"
    FORM_PLACEHOLDER = "form_placeholder"
    OTHER = "other"


class LayoutKind(str, Enum):
    """Common source-neutral section and region layouts."""

    STACK = "stack"
    GRID = "grid"
    FLEX = "flex"
    SPLIT = "split"
    CAROUSEL = "carousel"
    FREEFORM = "freeform"
    OTHER = "other"


class MediaPosition(str, Enum):
    """Position of editorial media relative to primary content."""

    TOP = "top"
    RIGHT = "right"
    BOTTOM = "bottom"
    LEFT = "left"
    BACKGROUND = "background"
    NONE = "none"


class Alignment(str, Enum):
    """Normalized content or item alignment."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    START = "start"
    END = "end"
    STRETCH = "stretch"
    SPACE_BETWEEN = "space_between"


class RepeatGroupKind(str, Enum):
    """Repeatable semantic structures recognized by the design engine."""

    CARD = "card"
    TESTIMONIAL = "testimonial"
    STAT = "stat"
    PRICING_PLAN = "pricing_plan"
    TEAM_MEMBER = "team_member"
    FAQ_ITEM = "faq_item"
    GALLERY_ITEM = "gallery_item"
    NAVIGATION_ITEM = "navigation_item"
    BLOG_POST = "blog_post"
    OTHER = "other"


class InteractionKind(str, Enum):
    """Interactions that can be inventoried without copying source scripts."""

    ACCORDION = "accordion"
    TABS = "tabs"
    CAROUSEL = "carousel"
    VIDEO_EMBED = "video_embed"
    MENU = "menu"
    FORM = "form"
    MODAL_TRIGGER = "modal_trigger"
    OTHER = "other"


class AssetKind(str, Enum):
    """Asset payload types referenced by design elements."""

    IMAGE = "image"
    VIDEO = "video"
    FONT = "font"
    SVG = "svg"
    DOCUMENT = "document"
    OTHER = "other"


class AssetRole(str, Enum):
    """Whether an asset is editable content or visual decoration."""

    EDITORIAL = "editorial"
    DECORATIVE = "decorative"


class NavigationVisibility(str, Enum):
    """Page-level navigation state captured from the source."""

    VISIBLE = "visible"
    HIDDEN = "hidden"
    UNKNOWN = "unknown"


class StyleProperty(str, Enum):
    """Normalized style properties supported by Design Document v1."""

    BACKGROUND_COLOR = "background_color"
    BACKGROUND_IMAGE = "background_image"
    BACKGROUND_POSITION = "background_position"
    TEXT_COLOR = "text_color"
    FONT_FAMILY = "font_family"
    FONT_SIZE = "font_size"
    FONT_WEIGHT = "font_weight"
    LINE_HEIGHT = "line_height"
    LETTER_SPACING = "letter_spacing"
    WIDTH = "width"
    HEIGHT = "height"
    MIN_HEIGHT = "min_height"
    MAX_WIDTH = "max_width"
    MARGIN = "margin"
    PADDING = "padding"
    ROW_GAP = "row_gap"
    COLUMN_GAP = "column_gap"
    TEXT_ALIGN = "text_align"
    ITEM_ALIGN = "item_align"
    BORDER = "border"
    BORDER_RADIUS = "border_radius"
    BOX_SHADOW = "box_shadow"
    OBJECT_FIT = "object_fit"
    OBJECT_POSITION = "object_position"
    POSITION = "position"
    OVERLAP = "overlap"
    TRANSFORM = "transform"
    ROTATION = "rotation"
    OPACITY = "opacity"
    OVERLAY_COLOR = "overlay_color"
    DISPLAY = "display"
    VISIBILITY = "visibility"
    FLEX_DIRECTION = "flex_direction"
    FLEX_WRAP = "flex_wrap"
    ORDER = "order"
    COLUMN_COUNT = "column_count"


class WarningSeverity(str, Enum):
    """Severity levels for non-fatal analysis findings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Viewport(_DesignModel):
    """Pixel dimensions used for a responsive observation."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)


class BoundingBox(_DesignModel):
    """Source geometry in CSS or Figma pixels."""

    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class Provenance(_DesignModel):
    """Trace from inferred design data back to HTML or Figma evidence."""

    source_kind: SourceKind
    method: ObservationMethod
    source_url: str | None = None
    css_selector: str | None = None
    source_attribute: str | None = None
    viewport: BreakpointName | None = None
    file_key: str | None = None
    page_node_id: str | None = None
    frame_node_id: str | None = None
    element_node_id: str | None = None
    component_id: str | None = None
    instance_id: str | None = None
    bounds: BoundingBox | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DesignSource(_DesignModel):
    """Identity and capture metadata for the input design."""

    kind: SourceKind
    identifier: str = Field(min_length=1)
    captured_at: AwareDatetime
    adapter_version: str = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class TokenValue(_DesignModel):
    """Named design token with optional provenance."""

    value: JsonValue
    provenance: list[Provenance] = Field(default_factory=list)


class TypographyToken(_DesignModel):
    """Typography evidence for a semantic role such as display or body."""

    role: str = Field(min_length=1)
    font_family: str | None = None
    font_size: str | None = None
    font_weight: int | str | None = None
    line_height: str | None = None
    letter_spacing: str | None = None
    provenance: list[Provenance] = Field(default_factory=list)


class DesignTokens(_DesignModel):
    """Source-level visual tokens shared across pages."""

    colors: dict[str, TokenValue] = Field(default_factory=dict)
    typography: list[TypographyToken] = Field(default_factory=list)
    spacing: dict[str, TokenValue] = Field(default_factory=dict)
    raw: dict[str, JsonValue] = Field(default_factory=dict)


class AssetRecord(_DesignModel):
    """A de-duplicated source asset or explicit unresolved asset."""

    id: str = Field(min_length=1)
    kind: AssetKind
    role: AssetRole
    source_url: str | None = None
    local_path: str | None = None
    mime_type: str | None = None
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    alt_text: str | None = None
    missing_reason: str | None = None
    provenance: list[Provenance] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_asset_location_or_reason(self) -> AssetRecord:
        """Require either a resolvable location or an explicit gap reason."""

        if not self.source_url and not self.local_path and not self.missing_reason:
            raise ValueError(
                "asset requires source_url, local_path, or missing_reason"
            )
        return self


class CandidateRole(_DesignModel):
    """Alternative semantic role considered for a section."""

    role: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class LayoutObservation(_DesignModel):
    """Normalized base layout for a section or nested region."""

    kind: LayoutKind
    contained: bool
    columns: int | None = Field(default=None, ge=1)
    media_position: MediaPosition | None = None
    alignment: Alignment | None = None
    full_bleed: bool = False
    direction: str | None = None
    wrap: bool | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ConditionBound(_DesignModel):
    """One bounded pixel-width comparison, e.g. ``max-width: 1023px``."""

    kind: ResponsiveConditionKind
    threshold_px: int = Field(gt=0, le=20000)


class ResponsiveCondition(_DesignModel):
    """A source CSS media condition and the cascade evidence behind it.

    Distinct from the sample breakpoint/viewport a ``ResponsiveObservation``
    was captured at: a breakpoint names *where a value was measured*, while
    a condition names *the authored width threshold a real stylesheet rule
    used to apply that value*. ``bounds`` is empty when ``status`` is
    ``UNRESOLVED`` and no bound could be parsed at all (e.g. an unsupported
    media expression); an ``OBSERVED`` condition always declares at least
    one bound. At most two bounds are supported (a single ``min-width`` or
    ``max-width`` comparison, or one of each forming a bounded range from
    nested/intersecting conditions).
    """

    bounds: list[ConditionBound] = Field(default_factory=list)
    status: ResponsiveConditionStatus
    important: bool = False
    rule_order: int = Field(ge=0)
    selector: str | None = None
    reason: str | None = None
    provenance: list[Provenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_condition(self) -> ResponsiveCondition:
        if self.status == ResponsiveConditionStatus.OBSERVED and not self.bounds:
            raise ValueError("an observed condition must declare at least one bound")
        if self.status == ResponsiveConditionStatus.UNRESOLVED and not self.reason:
            raise ValueError("an unresolved condition must explain why attribution failed")
        if len(self.bounds) > 2:
            raise ValueError("a condition may declare at most two width bounds")
        kinds = [bound.kind for bound in self.bounds]
        if len(set(kinds)) != len(kinds):
            raise ValueError("a condition cannot repeat the same bound kind")
        if self.bounds:
            lower = max(
                (b.threshold_px for b in self.bounds if b.kind == ResponsiveConditionKind.MIN_WIDTH),
                default=0,
            )
            upper = min(
                (b.threshold_px for b in self.bounds if b.kind == ResponsiveConditionKind.MAX_WIDTH),
                default=None,
            )
            if upper is not None and lower >= upper:
                raise ValueError("condition bounds describe an empty width range")
        return self


class StyleObservation(_DesignModel):
    """A supported style value and the evidence that produced it."""

    property: StyleProperty
    value: JsonValue
    status: EvidenceStatus = EvidenceStatus.OBSERVED
    confidence: float = Field(default=1.0, ge=0, le=1)
    condition: ResponsiveCondition | None = None
    provenance: list[Provenance] = Field(default_factory=list)


class StyleSet(_DesignModel):
    """Observed styles plus unsupported CSS retained without applying it."""

    observations: list[StyleObservation] = Field(default_factory=list)
    raw: dict[str, JsonValue] = Field(default_factory=dict)


class ContentElement(_DesignModel):
    """Visitor-facing content with semantic ownership and provenance."""

    id: str = Field(min_length=1)
    kind: ContentKind
    role: str = Field(min_length=1)
    value: JsonValue | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    asset_id: str | None = None
    group_id: str | None = None
    order: int = Field(ge=0)
    style: StyleSet = Field(default_factory=StyleSet)
    provenance: list[Provenance]
    confidence: float = Field(ge=0, le=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class LayoutRegion(_DesignModel):
    """A nested non-repeating owner for content elements."""

    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    order: int = Field(ge=0)
    layout: LayoutObservation
    parent_region_id: str | None = None
    provenance: list[Provenance] = Field(default_factory=list)


class RepeatGroupItem(_DesignModel):
    """One repeat instance mapping semantic fields to element IDs."""

    id: str = Field(min_length=1)
    fields: dict[str, str | list[str]]
    provenance: list[Provenance] = Field(default_factory=list)


class RepeatGroup(_DesignModel):
    """Relationship-preserving collection of repeated design items."""

    id: str = Field(min_length=1)
    kind: RepeatGroupKind
    items: list[RepeatGroupItem] = Field(
        min_length=1, json_schema_extra={"x-unique-by": "id"}
    )
    provenance: list[Provenance] = Field(default_factory=list)


class ResponsiveObservation(_DesignModel):
    """Breakpoint delta from a section's base layout and styles."""

    breakpoint: BreakpointName
    viewport: Viewport
    status: EvidenceStatus
    layout_changes: dict[str, JsonValue] = Field(default_factory=dict)
    style: StyleSet = Field(default_factory=StyleSet)
    hidden: bool | None = None
    # Section-wide condition ownership, distinct from a single property's own
    # `StyleObservation.condition`: set only when the whole section-level
    # delta (e.g. `layout_changes`/`hidden`, not one style property) is known
    # to be gated by one proven or explicitly unresolved width condition.
    section_condition: ResponsiveCondition | None = None
    provenance: list[Provenance] = Field(default_factory=list)


class DecorativeLayer(_DesignModel):
    """Non-editorial visual layer associated with a section."""

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    order: int = Field(ge=0)
    asset_id: str | None = None
    style: StyleSet = Field(default_factory=StyleSet)
    provenance: list[Provenance]
    confidence: float = Field(ge=0, le=1)


class Interaction(_DesignModel):
    """Source interaction inventory and native-representation status."""

    id: str = Field(min_length=1)
    kind: InteractionKind
    target_element_ids: list[str] = Field(default_factory=list)
    native_representation_known: bool
    status: EvidenceStatus = EvidenceStatus.OBSERVED
    details: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: list[Provenance]
    confidence: float = Field(ge=0, le=1)


class Section(_DesignModel):
    """Ordered semantic section within a design page."""

    id: str = Field(min_length=1)
    order: int = Field(ge=0)
    semantic_role: str = Field(min_length=1)
    role_confidence: float = Field(ge=0, le=1)
    candidate_roles: list[CandidateRole]
    layout: LayoutObservation
    content: list[ContentElement] = Field(json_schema_extra={"x-unique-by": "id"})
    regions: list[LayoutRegion] = Field(
        default_factory=list, json_schema_extra={"x-unique-by": "id"}
    )
    groups: list[RepeatGroup] = Field(json_schema_extra={"x-unique-by": "id"})
    style: StyleSet
    responsive: list[ResponsiveObservation]
    decorative_layers: list[DecorativeLayer] = Field(
        json_schema_extra={"x-unique-by": "id"}
    )
    interactions: list[Interaction] = Field(json_schema_extra={"x-unique-by": "id"})
    provenance: list[Provenance]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class SeoMetadata(_DesignModel):
    """SEO metadata available from a live page or design annotation."""

    title: str | None = None
    description: str | None = None
    canonical_url: str | None = None
    robots: str | None = None
    open_graph: dict[str, str] = Field(default_factory=dict)


class Page(_DesignModel):
    """A source page or page-like Figma frame."""

    id: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    title: str = Field(min_length=1)
    slug: str
    parent_page_id: str | None = None
    sections: list[Section] = Field(json_schema_extra={"x-unique-by": "id"})
    breakpoints: list[BreakpointName]
    navigation_visibility: NavigationVisibility
    seo: SeoMetadata | None = None
    provenance: list[Provenance]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DesignWarning(_DesignModel):
    """Non-fatal extraction or translation issue."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: WarningSeverity = WarningSeverity.WARNING
    path: str | None = None
    provenance: list[Provenance] = Field(default_factory=list)


class DesignAnalysis(_DesignModel):
    """Aggregate quality signals produced during design analysis."""

    section_confidence_mean: float = Field(ge=0, le=1)
    unsupported_traits: list[str]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DesignDocument(_DesignModel):
    """Public Design Document v1 intermediate representation."""

    schema_version: str = Field(pattern=r"^1\.0$")
    source: DesignSource
    tokens: DesignTokens
    assets: list[AssetRecord] = Field(json_schema_extra={"x-unique-by": "id"})
    pages: list[Page] = Field(json_schema_extra={"x-unique-by": "id"})
    warnings: list[DesignWarning]
    analysis: DesignAnalysis

    @model_validator(mode="after")
    def validate_references_and_identifiers(self) -> DesignDocument:
        """Reject duplicate IDs and dangling references with source paths."""

        seen: dict[str, str] = {}
        asset_ids = {asset.id for asset in self.assets}

        def register(identifier: str, path: str) -> None:
            previous_path = seen.get(identifier)
            if previous_path is not None:
                raise ValueError(
                    f"duplicate id {identifier!r} at {path}; first declared at "
                    f"{previous_path}"
                )
            seen[identifier] = path

        for asset_index, asset in enumerate(self.assets):
            register(asset.id, f"assets[{asset_index}].id")

        page_ids = {page.id for page in self.pages}
        for page_index, page in enumerate(self.pages):
            page_path = f"pages[{page_index}]"
            register(page.id, f"{page_path}.id")
            if page.parent_page_id is not None and page.parent_page_id not in page_ids:
                raise ValueError(
                    f"{page_path}.parent_page_id points to missing page "
                    f"{page.parent_page_id!r}"
                )

            for section_index, section in enumerate(page.sections):
                section_path = f"{page_path}.sections[{section_index}]"
                register(section.id, f"{section_path}.id")
                element_ids = {element.id for element in section.content}
                group_ids = {group.id for group in section.groups}
                region_ids = {region.id for region in section.regions}
                owner_ids = group_ids | region_ids

                for element_index, element in enumerate(section.content):
                    element_path = f"{section_path}.content[{element_index}]"
                    register(element.id, f"{element_path}.id")
                    if element.group_id is not None and element.group_id not in owner_ids:
                        raise ValueError(
                            f"{element_path}.group_id points to missing group or "
                            f"region {element.group_id!r}"
                        )
                    if element.asset_id is not None and element.asset_id not in asset_ids:
                        raise ValueError(
                            f"{element_path}.asset_id points to missing asset "
                            f"{element.asset_id!r}"
                        )

                for region_index, region in enumerate(section.regions):
                    region_path = f"{section_path}.regions[{region_index}]"
                    register(region.id, f"{region_path}.id")
                    if (
                        region.parent_region_id is not None
                        and region.parent_region_id not in region_ids
                    ):
                        raise ValueError(
                            f"{region_path}.parent_region_id points to missing region "
                            f"{region.parent_region_id!r}"
                        )

                for group_index, group in enumerate(section.groups):
                    group_path = f"{section_path}.groups[{group_index}]"
                    register(group.id, f"{group_path}.id")
                    for item_index, item in enumerate(group.items):
                        item_path = f"{group_path}.items[{item_index}]"
                        register(item.id, f"{item_path}.id")
                        for field_name, reference in item.fields.items():
                            references = reference if isinstance(reference, list) else [reference]
                            for element_id in references:
                                if element_id not in element_ids:
                                    raise ValueError(
                                        f"{item_path}.fields[{field_name!r}] points to "
                                        f"missing element {element_id!r}"
                                    )

                for layer_index, layer in enumerate(section.decorative_layers):
                    layer_path = f"{section_path}.decorative_layers[{layer_index}]"
                    register(layer.id, f"{layer_path}.id")
                    if layer.asset_id is not None and layer.asset_id not in asset_ids:
                        raise ValueError(
                            f"{layer_path}.asset_id points to missing asset "
                            f"{layer.asset_id!r}"
                        )

                for interaction_index, interaction in enumerate(section.interactions):
                    interaction_path = f"{section_path}.interactions[{interaction_index}]"
                    register(interaction.id, f"{interaction_path}.id")
                    for target_index, element_id in enumerate(
                        interaction.target_element_ids
                    ):
                        if element_id not in element_ids:
                            raise ValueError(
                                f"{interaction_path}.target_element_ids[{target_index}] "
                                f"points to missing element {element_id!r}"
                            )

        return self
