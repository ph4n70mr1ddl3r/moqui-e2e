#!/usr/bin/env python3
"""
Generate OpenAPI 3.0 spec from Moqui REST XML definitions.

Parses mantle.rest.xml and headless.rest.xml to produce a complete
OpenAPI specification for the Headless ERP API.

Usage:
    python3 tools/generate-openapi.py [--output openapi.yaml]
"""

import xml.etree.ElementTree as ET
import sys
import os
import yaml
import argparse
from collections import OrderedDict


# ── YAML helpers ──────────────────────────────────────────────────────────────

def represent_ordereddict(dumper, data):
    return dumper.represent_mapping('tag:yaml.org,2002:map', data.items())

yaml.add_representer(OrderedDict, represent_ordereddict)


def od(**kwargs):
    """Create OrderedDict, dropping None values."""
    return OrderedDict((k, v) for k, v in kwargs.items() if v is not None)


# ── XML → OpenAPI conversion ─────────────────────────────────────────────────

HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete'}

# Summary descriptions for known service/entity patterns
SERVICE_SUMMARIES = {
    # Headless services
    'headless.report.ReportServices.get#HealthStatus': 'System health check',
    'headless.auth.AuthServices.create#ApiKey': 'Create a new API key',
    'headless.auth.AuthServices.validate#ApiKey': 'Validate an API key',
    'headless.auth.AuthServices.revoke#ApiKey': 'Revoke an API key',
    'headless.auth.AuthServices.rotate#ApiKey': 'Rotate an API key (generates new secret)',
    'headless.webhook.WebhookServices.register#Webhook': 'Register a new webhook endpoint',
    'headless.webhook.WebhookServices.update#Webhook': 'Update webhook endpoint configuration',
    'headless.webhook.WebhookServices.retry#FailedWebhooks': 'Retry all failed webhook deliveries',
    'headless.report.ReportServices.get#DashboardStats': 'Get aggregate dashboard statistics',
    'headless.report.ReportServices.get#RecentActivity': 'Get recent activity feed',
}

ENTITY_OPERATION_SUMMARIES = {
    'list': 'List records',
    'one': 'Get a single record',
    'create': 'Create a new record',
    'update': 'Update an existing record',
    'delete': 'Delete a record',
    'store': 'Create or update a record',
}


def get_method_summary(method_elem, http_method):
    """Generate a summary string for a method element."""
    # Find inner entity or service child
    entity_child = method_elem.find('entity')
    service_child = method_elem.find('service')

    service_name = service_child.get('name') if service_child is not None else None
    entity_name = entity_child.get('name') if entity_child is not None else None
    operation = entity_child.get('operation') if entity_child is not None else None

    # Check known services
    if service_name and service_name in SERVICE_SUMMARIES:
        return SERVICE_SUMMARIES[service_name]

    # Generate from service name
    if service_name:
        # mantle.order.OrderServices.create#Order → Create Order
        parts = service_name.split('.')
        svc = parts[-1] if parts else service_name
        if '#' in svc:
            verb, noun = svc.split('#', 1)
            return f"{verb.capitalize()} {noun}"
        return svc

    # Entity operations — include entity name
    if operation and operation in ENTITY_OPERATION_SUMMARIES:
        summary = ENTITY_OPERATION_SUMMARIES[operation]
        if entity_name:
            # Shorten entity name: headless.auth.ApiKeyDetail → ApiKeyDetail
            short = entity_name.split('.')[-1]
            summary = f"{summary} ({short})"
        return summary

    return f"{http_method.upper()} operation"


def make_schema_ref(name):
    """Create a schema reference."""
    return od(**{'$ref': f'#/components/schemas/{name}'})


def build_path_method(method_elem, http_method, path_params, resource_desc=None):
    """Build an OpenAPI operation object from a <method> element."""
    # The method element may have require-authentication directly, or on the inner element
    require_auth = method_elem.get('require-authentication', '')
    # Also check inner entity/service child
    inner = method_elem.find('entity')
    if inner is None:
        inner = method_elem.find('service')
    if inner is not None and not require_auth:
        require_auth = inner.get('require-authentication', '')
    is_anon = require_auth in ('anonymous-all', 'anonymous-view')
    description = method_elem.get('description') or (inner.get('description') if inner is not None else None)
    service_name = inner.get('name') if inner is not None else method_elem.get('name')
    entity_name = inner.get('name') if inner is not None and inner.tag == 'entity' else None
    operation = inner.get('operation', '') if inner is not None else method_elem.get('operation', '')

    summary = get_method_summary(method_elem, http_method)

    operation_obj = od(summary=summary)

    # Tags based on first resource segment
    operation_obj['tags'] = []

    # Description
    if description:
        operation_obj['description'] = description

    # Security
    if not is_anon:
        operation_obj['security'] = [{'BearerAuth': []}, {'BasicAuth': []}]

    # Schema overrides for known endpoints
    response_schema = None
    request_schema = None
    if service_name == 'headless.report.ReportServices.get#HealthStatus':
        response_schema = make_schema_ref('HealthStatus')
    elif service_name == 'headless.auth.AuthServices.create#ApiKey':
        response_schema = make_schema_ref('ApiKeyCreateResponse')
        request_schema = make_schema_ref('ApiKeyCreateRequest')
    elif entity_name == 'headless.auth.ApiKeyDetail' and operation == 'list':
        response_schema = od(type='array', items=make_schema_ref('ApiKeyDetail'))
    elif entity_name == 'headless.auth.ApiKeyDetail' and operation == 'one':
        response_schema = make_schema_ref('ApiKeyDetail')
    elif entity_name == 'headless.webhook.WebhookDeliveryDetail' and operation == 'list':
        response_schema = od(type='array', items=make_schema_ref('WebhookDelivery'))
    elif entity_name == 'headless.webhook.WebhookDeliveryDetail' and operation == 'one':
        response_schema = make_schema_ref('WebhookDelivery')
    elif service_name == 'headless.report.ReportServices.get#DashboardStats':
        response_schema = make_schema_ref('DashboardStats')
    elif service_name == 'headless.webhook.WebhookServices.register#Webhook':
        request_schema = make_schema_ref('WebhookRegisterRequest')

    # Parameters (path params)
    all_params = []
    for pp in path_params:
        all_params.append(od(
            name=pp,
            **{'in': 'path'},
            required=True,
            schema=od(type='string'),
            description=f'{pp} identifier'
        ))

    # For list operations, add common query params
    if operation == 'list':
        all_params.extend([
            od(name='pageIndex', **{'in': 'query'}, required=False,
               schema=od(type='integer', default=0), description='Page index (0-based)'),
            od(name='pageSize', **{'in': 'query'}, required=False,
               schema=od(type='integer', default=20), description='Page size'),
            od(name='orderBy', **{'in': 'query'}, required=False,
               schema=od(type='string'), description='Field(s) to sort by (comma-separated, prefix - for desc)'),
        ])

    if all_params:
        operation_obj['parameters'] = all_params

    # Request body for POST/PUT/PATCH
    if http_method in ('post', 'put', 'patch'):
        content_type = 'application/json'
        req_schema = request_schema or od(type='object', additionalProperties=True)
        operation_obj['requestBody'] = od(
            required=True,
            content=od(**{
                content_type: od(schema=req_schema)
            })
        )

    # Responses
    responses = OrderedDict()

    if http_method == 'get':
        if operation == 'list':
            schema = response_schema or od(type='array', items=od(type='object'))
            responses['200'] = od(
                description='List of records',
                content=od(**{'application/json': od(schema=schema)})
            )
        else:
            schema = response_schema or od(type='object')
            responses['200'] = od(
                description='Record details',
                content=od(**{'application/json': od(schema=schema)})
            )
    elif http_method == 'post':
        schema = response_schema or od(type='object')
        responses['200'] = od(
            description='Operation result',
            content=od(**{'application/json': od(schema=schema)})
        )
    elif http_method in ('put', 'patch'):
        schema = response_schema or od(type='object')
        responses['200'] = od(
            description='Updated record',
            content=od(**{'application/json': od(schema=schema)})
        )
    elif http_method == 'delete':
        responses['200'] = od(
            description='Deletion confirmed',
            content=od(**{'application/json': od(
                schema=od(type='object')
            )})
        )

    responses['401'] = od(description='Authentication required')
    responses['403'] = od(description='Insufficient permissions')
    responses['404'] = od(description='Resource not found')
    responses['500'] = od(description='Internal server error')

    # Remove auth-related error responses for anonymous endpoints
    if is_anon:
        responses.pop('401', None)
        responses.pop('403', None)

    operation_obj['responses'] = responses

    return operation_obj


def walk_resource(elem, base_path, path_params, tag, paths, schemas):
    """Recursively walk the XML resource tree and build OpenAPI paths."""
    name = elem.get('name')
    is_id = elem.tag == 'id'
    description = elem.get('description')

    # Build current path
    if is_id:
        current_path = f'{base_path}/{{{name}}}'
        current_params = path_params + [name]
    else:
        current_path = f'{base_path}/{name}'
        current_params = path_params[:]

    # Use resource name as tag if it's a top-level named resource
    current_tag = tag
    if name and not is_id and tag is None:
        # Capitalize nicely: 'apiKeys' → 'API Keys', 'health' → 'Health'
        label = name
        # Split camelCase into words
        import re
        words = re.sub(r'([a-z])([A-Z])', r'\1 \2', label).split()
        current_tag = ' '.join(w.capitalize() for w in words)

    # Process methods on this resource
    for child in elem:
        if child.tag == 'method':
            http_method = child.get('type')
            if http_method and http_method in HTTP_METHODS:
                op = build_path_method(child, http_method, current_params, description)
                if current_tag:
                    op['tags'] = [current_tag]

                if current_path not in paths:
                    paths[current_path] = OrderedDict()
                paths[current_path][http_method] = op
        elif child.tag in ('resource', 'id'):
            walk_resource(child, current_path, current_params, current_tag, paths, schemas)


def parse_rest_xml(filepath, mount_point):
    """Parse a Moqui REST XML file and return paths + schemas."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    paths = OrderedDict()
    schemas = OrderedDict()

    resource_name = root.get('name', 'api')
    resource_desc = root.get('description', '')
    version = root.get('version', '1.0.0')

    base_path = mount_point.rstrip('/')

    # Walk all child resources
    for child in root:
        if child.tag in ('resource', 'id'):
            tag = resource_name if child.tag == 'resource' else resource_name
            walk_resource(child, base_path, [], None, paths, schemas)

    return paths, schemas, resource_name, resource_desc, version


def build_components():
    """Build OpenAPI components (security schemes, schemas)."""
    components = OrderedDict()

    # Security schemes
    components['securitySchemes'] = OrderedDict([
        ('BearerAuth', od(
            type='http',
            scheme='bearer',
            bearerFormat='hlp_ prefixed API key',
            description='API key with hlp_ prefix, obtained from POST /headless/apiKeys/create'
        )),
        ('BasicAuth', od(
            type='http',
            scheme='basic',
            description='HTTP Basic authentication (username:password)'
        )),
    ])

    # Common schemas
    components['schemas'] = OrderedDict([
        ('Error', od(
            type='object',
            required=['errorCode', 'errors'],
            properties=OrderedDict([
                ('errorCode', od(type='integer', description='HTTP status code')),
                ('errors', od(type='string', description='Error message')),
            ])
        )),
        ('ApiKeyCreateRequest', od(
            type='object',
            required=['userId'],
            properties=OrderedDict([
                ('userId', od(type='string', description='User ID to associate with the key')),
                ('name', od(type='string', description='Human-readable key name')),
                ('scopes', od(type='string', description='Comma-separated permission scopes')),
                ('expiresInDays', od(type='integer', description='Days until key expires (default: 365)')),
            ])
        )),
        ('ApiKeyCreateResponse', od(
            type='object',
            properties=OrderedDict([
                ('apiKeyId', od(type='string', description='Internal key ID')),
                ('rawKey', od(type='string', description='The raw API key (hlp_ prefix). Store this securely — it cannot be retrieved again.')),
                ('name', od(type='string')),
                ('expiresDate', od(type='string', format='date-time')),
            ])
        )),
        ('ApiKeyDetail', od(
            type='object',
            properties=OrderedDict([
                ('apiKeyId', od(type='string')),
                ('userId', od(type='string')),
                ('name', od(type='string')),
                ('prefix', od(type='string', description='First 8 chars of raw key for identification')),
                ('scopes', od(type='string')),
                ('isActive', od(type='string', description='Y/N')),
                ('createdDate', od(type='string', format='date-time')),
                ('expiresDate', od(type='string', format='date-time')),
                ('lastUsedDate', od(type='string', format='date-time')),
            ])
        )),
        ('WebhookRegisterRequest', od(
            type='object',
            required=['name', 'targetUrl', 'subscribedEvents'],
            properties=OrderedDict([
                ('name', od(type='string', description='Webhook endpoint name')),
                ('targetUrl', od(type='string', format='uri', description='URL to receive POST payloads')),
                ('subscribedEvents', od(type='string', description='Comma-separated event names')),
                ('secret', od(type='string', description='HMAC signing secret (auto-generated if omitted)')),
                ('active', od(type='string', description='Y/N, default Y')),
            ])
        )),
        ('WebhookRegisterResponse', od(
            type='object',
            properties=OrderedDict([
                ('webhookId', od(type='string')),
                ('secret', od(type='string', description='HMAC signing secret')),
            ])
        )),
        ('WebhookDelivery', od(
            type='object',
            properties=OrderedDict([
                ('deliveryId', od(type='string')),
                ('webhookId', od(type='string')),
                ('webhookName', od(type='string')),
                ('targetUrl', od(type='string', format='uri')),
                ('eventName', od(type='string')),
                ('payload', od(type='string', description='JSON payload sent')),
                ('statusCode', od(type='integer', description='HTTP status from target')),
                ('responseBody', od(type='string', description='Response from target')),
                ('attemptCount', od(type='integer')),
                ('statusEnumId', od(type='string', enum=['WdsPending', 'WdsDelivered', 'WdsFailed'])),
                ('durationMs', od(type='integer', description='Delivery duration in milliseconds')),
                ('createdDate', od(type='string', format='date-time')),
                ('deliveredDate', od(type='string', format='date-time')),
            ])
        )),
        ('HealthStatus', od(
            type='object',
            properties=OrderedDict([
                ('status', od(type='string', enum=['UP', 'DOWN'])),
                ('database', od(type='string')),
                ('serverTime', od(type='string', format='date-time')),
                ('version', od(type='string')),
            ])
        )),
        ('DashboardStats', od(
            type='object',
            properties=OrderedDict([
                ('orderCount', od(type='integer')),
                ('revenue', od(type='number')),
                ('pendingShipments', od(type='integer')),
                ('activeWebhooks', od(type='integer')),
                ('apiCalls24h', od(type='integer')),
            ])
        )),
        ('WebhookEvent', od(
            type='object',
            required=['event', 'timestamp', 'data'],
            properties=OrderedDict([
                ('event', od(type='string', description='Event name (e.g. order.placed)',
                    enum=['order.placed', 'order.approved', 'order.completed', 'order.cancelled',
                          'shipment.shipped', 'shipment.delivered', 'inventory.updated',
                          'payment.received', 'invoice.created', 'invoice.sent'])),
                ('timestamp', od(type='string', format='date-time')),
                ('data', od(type='object', description='Event-specific payload data')),
            ])
        )),
    ])

    return components


def generate_openapi(rest_files, output_path):
    """Generate the complete OpenAPI spec."""
    all_paths = OrderedDict()

    info_version = '1.0.0'

    for filepath, mount_point in rest_files:
        if not os.path.exists(filepath):
            print(f"Warning: {filepath} not found, skipping", file=sys.stderr)
            continue

        paths, schemas, res_name, res_desc, version = parse_rest_xml(filepath, mount_point)
        all_paths.update(paths)
        info_version = version

    spec = OrderedDict([
        ('openapi', '3.0.3'),
        ('info', od(
            title='Headless ERP API',
            version=info_version,
            description=(
                '# Headless ERP — REST API\n\n'
                'A headless ERP system built on Moqui Framework + Mantle UDM/USL, '
                'exposing all ERP functionality via REST API.\n\n'
                '## Authentication\n\n'
                'All endpoints require authentication except `GET /headless/health`. '
                'Two methods are supported:\n\n'
                '1. **Bearer Token** — Pass an API key: `Authorization: Bearer hlp_xxxx...`\n'
                '2. **HTTP Basic** — Pass username:password\n\n'
                'API keys are managed via `POST /headless/apiKeys/create`.\n\n'
                '## Webhook Events\n\n'
                'Register webhook endpoints to receive real-time notifications when business events occur:\n\n'
                '| Event | Trigger |\n'
                '|---|---|\n'
                '| `order.placed` | Order status → OrderPlaced |\n'
                '| `order.approved` | Order status → OrderApproved |\n'
                '| `order.completed` | Order status → OrderCompleted |\n'
                '| `order.cancelled` | Order status → OrderCancelled |\n'
                '| `shipment.shipped` | Shipment status → ShipShipped |\n'
                '| `shipment.delivered` | Shipment status → ShipDelivered |\n'
                '| `inventory.updated` | Asset status → AssetAvailable |\n'
                '| `payment.received` | Payment status → PmntDelivered |\n'
                '| `invoice.created` | Invoice status → InvoiceReady |\n'
                '| `invoice.sent` | Invoice status → InvoiceInProcess |\n\n'
                'Webhook payloads are HMAC-SHA256 signed. See the `WebhookEvent` schema for details.\n'
            ),
            contact=od(
                name='Headless ERP',
                url='https://github.com/ph4n70mr1ddl3r/headless',
            ),
            license=od(
                name='CC0-1.0',
                url='https://creativecommons.org/publicdomain/zero/1.0/',
            ),
        )),
        ('servers', [
            od(url='http://localhost:8080/rest/s1', description='Development server'),
            od(url='https://erp.example.com/rest/s1', description='Production server'),
        ]),
        ('tags', [
            od(name='Health', description='System health checks (no authentication required)'),
            od(name='Api Keys', description='API key lifecycle management for machine-to-machine authentication'),
            od(name='Webhooks', description='Outbound webhook endpoint registration and delivery tracking'),
            od(name='Audit', description='API audit trail and request logging'),
            od(name='Stats', description='Dashboard statistics and metrics'),
            od(name='Activity', description='Recent activity feed'),
            od(name='Rate Limits', description='Rate limit configuration per endpoint/API key'),
            od(name='Parties', description='Customers, Suppliers, Contacts, Employees'),
            od(name='Products', description='Products, Categories, Features, Stores, Assets'),
            od(name='Assets', description='Inventory, Supplies, Equipment tracking'),
            od(name='Orders', description='Purchase and Sales Orders lifecycle'),
            od(name='Shipments', description='Incoming and Outgoing shipments'),
            od(name='Returns', description='Customer and Vendor returns'),
            od(name='Invoices', description='Payable and Receivable invoices'),
            od(name='Payments', description='Incoming and Outgoing payments'),
            od(name='Financial Accounts', description='Credit accounts, Gift cards, Deposits, Loans'),
            od(name='Gl', description='General Ledger transactions and reports'),
            od(name='Work Efforts', description='Projects, Tasks, Events, Production Runs'),
            od(name='Facilities', description='Facilities and locations'),
            od(name='Lookup', description='Lookup entities by ID'),
            od(name='My', description='Current user information'),
        ]),
        ('paths', all_paths),
        ('components', build_components()),
    ])

    # Write YAML
    with open(output_path, 'w') as f:
        yaml.dump(
            dict(spec),
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

    # Count stats
    path_count = len(all_paths)
    op_count = sum(len(ops) for ops in all_paths.values())
    print(f"Generated OpenAPI spec: {path_count} paths, {op_count} operations → {output_path}")

    return spec


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate OpenAPI spec from Moqui REST XML')
    parser.add_argument('--output', '-o', default='openapi.yaml', help='Output file path')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)

    rest_files = [
        (os.path.join(project_dir, 'runtime/component/headless-erp/service/headless.rest.xml'), '/headless'),
        (os.path.join(project_dir, 'runtime/component/mantle-usl/service/mantle.rest.xml'), '/mantle'),
    ]

    output_path = os.path.join(project_dir, args.output)
    generate_openapi(rest_files, output_path)
