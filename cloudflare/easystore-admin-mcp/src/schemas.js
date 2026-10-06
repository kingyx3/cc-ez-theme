// Shared JSON schemas for the explicit admin operation registry.

const money = {"anyOf": [{"type": "number", "minimum": 0}, {"type": "string", "pattern": "^\\d+(\\.\\d+)?$"}]};

const idList = {"anyOf": [{"type": "string", "maxLength": 4096}, {"type": "array", "items": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"}]}}, {"type": "null"}]};

const nullableRange = {"anyOf": [{"type": "null"}, {"type": "string"}, {"type": "object"}, {"type": "array"}]};

export const pathSchema = key => ({ type: "object", properties: { [key]: { type: "string", pattern: "^[A-Za-z0-9_-]{1,128}$" } }, required: [key], additionalProperties: false });

export const readQuery = {
  type: "object",
  properties: {
    q: {"type": "string", "maxLength": 2048},
    fields: {"type": "string", "maxLength": 2048},
    sort: {"type": "string", "maxLength": 2048},
    start_date: {"type": "string", "maxLength": 2048},
    end_date: {"type": "string", "maxLength": 2048},
    status: {"type": "string", "maxLength": 2048},
    type: {"type": "string", "maxLength": 2048},
    types: {"type": "string", "maxLength": 2048},
    targets: {"type": "string", "maxLength": 2048},
    usage_limits: {"type": "string", "maxLength": 2048},
    visibility: {"type": "string", "maxLength": 2048},
    channels: {"type": "string", "maxLength": 2048},
    pos_location_ids: {"type": "string", "maxLength": 2048},
    extras: {"type": "string", "maxLength": 2048},
    category: {"type": "string", "maxLength": 2048},
    discount_methods: {"type": "string", "maxLength": 2048},
    workflow_ids: {"type": "string", "maxLength": 2048},
    voucher_codes: {"type": "string", "maxLength": 2048},
    product_ids: {"type": "string", "maxLength": 2048},
    variant_ids: {"type": "string", "maxLength": 2048},
    collection_ids: {"type": "string", "maxLength": 2048},
    customer_ids: {"type": "string", "maxLength": 2048},
    location_ids: {"type": "string", "maxLength": 2048},
    order_ids: {"type": "string", "maxLength": 2048},
    ids: {"type": "string", "maxLength": 2048},
    filter: {"type": "string", "maxLength": 2048},
    created_at_min: {"type": "string", "maxLength": 2048},
    created_at_max: {"type": "string", "maxLength": 2048},
    updated_at_min: {"type": "string", "maxLength": 2048},
    updated_at_max: {"type": "string", "maxLength": 2048},
    financial_status: {"type": "string", "maxLength": 2048},
    fulfillment_status: {"type": "string", "maxLength": 2048},
    tags: {"type": "string", "maxLength": 2048},
    vendor: {"type": "string", "maxLength": 2048},
    brand: {"type": "string", "maxLength": 2048},
    page: {"type": "integer", "minimum": 1},
    limit: {"type": "integer", "minimum": 1, "maximum": 50},
  },
  additionalProperties: false,
};

export const checkoutQuery = {
  type: "object",
  properties: {
    page: {"type": "integer", "minimum": 1},
    limit: {"type": "integer", "minimum": 1, "maximum": 50},
    start_date: {"type": "string", "maxLength": 64},
    end_date: {"type": "string", "maxLength": 64},
    sort: {"type": "string", "enum": ["created_at.desc"]},
  },
  additionalProperties: false,
};

export const discountCreate = {
  type: "object",
  properties: {
    id: {"type": "integer", "minimum": 0},
    title: {"type": "string", "minLength": 1, "maxLength": 255},
    description: {"type": "string"},
    prerequisite_quantity_range: nullableRange,
    prerequisite_subtotal_range: nullableRange,
    prerequisite_order_ids: idList,
    prerequisite_product_ids: idList,
    prerequisite_variant_ids: idList,
    prerequisite_collection_ids: idList,
    promotion_applies_to: {"type": "string", "enum": ["purchased_item", "add_on_item", "order_subtotal", "order_shipping_fee"]},
    entitled_quantity: money,
    target_type: {"type": "string", "enum": ["line_item", "credit", "free", "shipping_line", "pickup"]},
    value_type: {"type": "string", "enum": ["fixed_amount", "percentage", "set_price", "free_of_charge"]},
    value: money,
    value_limit: money,
    entitled_regions: {"type": "object"},
    entitled_country_ids: idList,
    channel_selection: {"type": "string", "pattern": "^(website|mobile|pos)(,(website|mobile|pos))*$"},
    prerequisite_location_ids: idList,
    prerequisite_locations: {"type": "array"},
    entitled_product_ids: idList,
    entitled_variant_ids: idList,
    entitled_collection_ids: idList,
    prerequisite_exclusion_variant_ids: idList,
    entitled_exclusion_variant_ids: idList,
    allocation_limit: money,
    starts_at: {"type": "string", "minLength": 1},
    ends_at: {"type": ["string", "null"]},
    discount_codes: {"type": ["array", "null"]},
    redemption_setting: {"type": ["object", "null"]},
    customer_selection: {"type": "string", "enum": ["all", "logged", "prerequisite_customer_group", "prerequisite_customer", "prerequisite_membership_tier"]},
    prerequisite_group_ids: idList,
    prerequisite_bir_citizen_group_ids: idList,
    prerequisite_customer_ids: idList,
    prerequisite_membership_tier_ids: idList,
    campaign_page_ids: idList,
    usage_limit: money,
    usage_limit_per_customer: money,
    is_show_in_voucher_shop: {"type": "boolean"},
  },
  required: ["title", "promotion_applies_to", "target_type", "value_type", "value", "channel_selection", "starts_at"],
  additionalProperties: false,
};

export const customerCreate = {
  type: "object",
  properties: {
    first_name: {"type": "string"},
    last_name: {"type": "string"},
    email: {"type": "string"},
    phone: {"type": "string"},
    country_code: {"type": "string"},
    gender: {"type": "string"},
    note: {"type": "string"},
    points_description: {"type": "string"},
    birthdate: {"type": ["string", "null"]},
    avatar_url: {"type": ["string", "null"]},
    address: {"type": "object", "properties": {"first_name": {"type": "string"}, "last_name": {"type": "string"}, "company": {"type": "string"}, "phone": {"type": "string"}, "address1": {"type": "string"}, "address2": {"type": "string"}, "province_code": {"type": "string"}, "province": {"type": "string"}, "city": {"type": "string"}, "zip": {"type": "string"}, "country_code": {"type": "string"}}, "additionalProperties": false},
    groups: {"type": "array"},
    selected_groups: {"type": "array"},
    attributes: {"type": "array"},
    membership_tier_id: {"type": ["integer", "null"]},
    store_credit: {"type": ["number", "string"]},
    points: {"type": ["number", "string"]},
  },
  required: ["first_name"],
  additionalProperties: false,
};

export const productCreate = {
  type: "object",
  properties: {
    title: {"type": "string"},
    body_html: {"type": "string"},
    description: {"type": "string"},
    handle: {"type": "string"},
    published_at: {"type": "string"},
    published_timestamp: {"type": "string"},
    note: {"type": "string"},
    id: {"type": "integer", "minimum": 1},
    highlight_data: {"type": ["object", "null"]},
    common_question_data: {"type": ["object", "null"]},
    taxable: {"type": "boolean"},
    inventory_management: {"type": "string", "enum": ["none", "easystore"]},
    inventory_policy: {"type": "boolean"},
    is_published: {"type": "integer", "enum": [0, 1, 2]},
    shipping_required: {"type": "boolean"},
    is_channel_available: {"type": "boolean"},
    collections: {"type": "array"},
    vendors: {"type": "array"},
    brands: {"type": "array"},
    tags: {"type": "array"},
    variant_types: {"type": "array"},
    channels: {"type": "array"},
    images: {"type": "array"},
    variants: {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {"sku": {"type": "string"}, "barcode": {"type": "string"}, "weight_unit": {"type": "string"}, "shelf": {"type": "string"}, "preparation_time_unit": {"type": "string"}, "name": {"type": ["string", "null"]}, "id": {"type": ["integer", "null"]}, "width": {"type": "number", "minimum": 0}, "height": {"type": "number", "minimum": 0}, "length": {"type": "number", "minimum": 0}, "weight": {"type": "number", "minimum": 0}, "price": {"type": "number", "minimum": 0}, "compare_at_price": {"type": "number", "minimum": 0}, "cost_price": {"type": "number", "minimum": 0}, "reserved_inventory_quantity": {"type": "number", "minimum": 0}, "inventory_quantity": {"type": "number", "minimum": 0}, "inventory_policy": {"type": "boolean"}, "taxable": {"type": "boolean"}, "shipping_required": {"type": "boolean"}, "is_enabled": {"type": "boolean"}, "is_deleted": {"type": "boolean"}, "inventory_levels": {"type": "array", "items": {"type": "object", "properties": {"location_id": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "string", "minLength": 1}]}, "inventory_quantity": {"type": "number"}, "reserved_inventory_quantity": {"type": "number", "minimum": 0}}, "required": ["location_id", "inventory_quantity"], "additionalProperties": false}}, "preparation_time_value": {"type": ["number", "null"]}, "option_values": {"type": "array", "items": {"type": "string"}}}, "required": ["price", "sku", "taxable", "shipping_required"], "additionalProperties": false}},
  },
  required: ["title", "variants", "taxable", "shipping_required", "inventory_management", "is_published"],
  additionalProperties: false,
};

export const discountUpdate = { ...discountCreate, properties: { ...discountCreate.properties, id: { type: "integer", minimum: 1 } }, required: ["id", ...discountCreate.required] };

const { required: customerRequired, ...customerPartial } = customerCreate;
export const customerUpdate = { ...customerPartial, minProperties: 1 };

// New products are always created unpublished; the worker has no right to publish them.
const { published_at, published_timestamp, ...productCreateProperties } = productCreate.properties;
export const productCreateUnpublished = { ...productCreate, properties: { ...productCreateProperties, is_published: { type: "integer", enum: [0] } } };

export const productUpdate = { ...productCreate, required: [...productCreate.required, "id"] };
