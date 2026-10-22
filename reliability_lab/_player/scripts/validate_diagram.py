"""Data and orthogonal route validation; Python standard library only."""
import math
import re

COLORS = {'cyan', 'blue', 'green', 'purple', 'pink', 'red'}
ID = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')


def validate(data):
    def need(ok, message):
        if not ok:
            raise ValueError(message)

    def text(value, name, nonempty=False):
        need(isinstance(value, str) and (not nonempty or bool(value.strip())), name + ' must be text')

    def number(value, name, minimum=None, maximum=None):
        need(type(value) in (int, float) and math.isfinite(value), name + ' must be a finite number')
        if minimum is not None:
            need(value >= minimum, name + ' is below the minimum')
        if maximum is not None:
            need(value <= maximum, name + ' is above the maximum')

    def ident(value, name):
        need(isinstance(value, str) and bool(ID.fullmatch(value)), name + ' must be a simple identifier')

    def array(value, name, nonempty=False):
        need(isinstance(value, list) and (not nonempty or len(value) > 0), name + ' must be an array')

    def point(value, name):
        need(isinstance(value, list) and len(value) == 2, name + ' must be [x,y]')
        number(value[0], name + '.x'); number(value[1], name + '.y')

    need(isinstance(data, dict), 'diagram must be an object')
    need(type(data.get('version')) is int and data['version'] == 1, 'version must be 1')
    text(data.get('title'), 'title', True)
    for key in ('subtitle', 'windowTitle'):
        if key in data:
            text(data[key], key)
    if 'simulated' in data:
        need(type(data['simulated']) is bool, 'simulated must be boolean')
    canvas = data.get('canvas')
    need(isinstance(canvas, dict), 'canvas must be an object')
    for key in ('width', 'height'):
        number(canvas.get(key), 'canvas.' + key, 1)
    nodes = {}; routes = {}; steps = set()
    array(data.get('nodes'), 'nodes', True)
    for n in data['nodes']:
        need(isinstance(n, dict), 'node must be an object')
        ident(n.get('id'), 'node.id'); need(n['id'] not in nodes, 'duplicate node: ' + n['id'])
        text(n.get('title'), n['id'] + '.title', True)
        need(n.get('color', 'cyan') in COLORS, 'unknown node color: ' + n['id'])
        need(n.get('kind', 'main') in {'info', 'main', 'decision', 'reviewer', 'worker'}, 'unknown node kind')
        b = n.get('bounds'); need(isinstance(b, list) and len(b) == 4, n['id'] + '.bounds must be [x,y,width,height]')
        for i, v in enumerate(b):
            number(v, n['id'] + '.bounds', 0 if i < 2 else 1)
        need(b[0]+b[2] <= canvas['width'] and b[1]+b[3] <= canvas['height'], n['id'] + ' lies outside canvas')
        for key in ('subtitle', 'state', 'operation', 'footer'):
            if key in n:
                text(n[key], n['id'] + '.' + key)
        array(n.get('lines', []), n['id'] + '.lines')
        for line in n.get('lines', []):
            text(line, 'line')
        array(n.get('rows', []), n['id'] + '.rows')
        for row in n.get('rows', []):
            need(isinstance(row, dict), 'row must be an object')
            text(row.get('label'), 'row.label'); text(row.get('value'), 'row.value')
        array(n.get('meters', []), n['id'] + '.meters')
        meter_ids = set()
        for meter in n.get('meters', []):
            need(isinstance(meter, dict), 'meter must be an object')
            ident(meter.get('id'), 'meter.id'); need(meter['id'] not in meter_ids, 'duplicate meter')
            meter_ids.add(meter['id']); text(meter.get('label'), 'meter.label')
            number(meter.get('value'), 'meter.value', 0, 1)
            if 'warningBelow' in meter:
                number(meter['warningBelow'], 'warningBelow', 0, 1)
        nodes[n['id']] = n
    entries = list(nodes.items())
    for i, (a, n) in enumerate(entries):
        x, y, w, h = n['bounds']
        for b, other in entries[i+1:]:
            xx, yy, ww, hh = other['bounds']
            need(not (max(x,xx) < min(x+w,xx+ww) and max(y,yy) < min(y+h,yy+hh)), a + ' overlaps ' + b)

    def boundary(p, b):
        x, y, w, h = b; px, py = p; eps = 1e-6
        return ((abs(px-x) < eps or abs(px-x-w) < eps) and y < py < y+h) or ((abs(py-y) < eps or abs(py-y-h) < eps) and x < px < x+w)

    segments = []
    array(data.get('routes'), 'routes')
    for r in data['routes']:
        need(isinstance(r, dict), 'route must be an object')
        ident(r.get('id'), 'route.id'); need(r['id'] not in routes, 'duplicate route: ' + r['id'])
        need(r.get('source') in nodes and r.get('target') in nodes, r['id'] + ': unknown source or target')
        need(r.get('color', 'cyan') in COLORS, 'unknown route color')
        pts = r.get('points'); array(pts, r['id'] + '.points', True); need(len(pts) >= 2, 'route needs two points')
        for p in pts:
            point(p, r['id'] + '.point')
            need(0 <= p[0] <= canvas['width'] and 0 <= p[1] <= canvas['height'], 'route point outside canvas')
        need(boundary(pts[0], nodes[r['source']]['bounds']), r['id'] + ': source endpoint must be on a non-corner border')
        need(boundary(pts[-1], nodes[r['target']]['bounds']), r['id'] + ': target endpoint must be on a non-corner border')
        for index, (a, b) in enumerate(zip(pts, pts[1:])):
            need(a != b, r['id'] + ': zero-length segment')
            need(a[0] == b[0] or a[1] == b[1], r['id'] + ': segments must be horizontal or vertical')
            if index > 0:
                before = pts[index-1]
                need((before[0] == a[0]) != (a[0] == b[0]), r['id'] + ': merge redundant collinear segments or remove U-turns')
            for nid, n in nodes.items():
                x, y, w, h = n['bounds']
                inside = (a[1] == b[1] and y < a[1] < y+h and max(min(a[0],b[0]),x) < min(max(a[0],b[0]),x+w)) or (a[0] == b[0] and x < a[0] < x+w and max(min(a[1],b[1]),y) < min(max(a[1],b[1]),y+h))
                need(not inside, r['id'] + ': route passes through ' + nid)
            segments.append((r['id'], index, a, b))
        if 'label' in r:
            text(r['label'], 'route.label'); point(r.get('labelAt'), 'route.labelAt')
        routes[r['id']] = r

    def intersection(a, b, c, d):
        horizontal_a = a[1] == b[1]; horizontal_b = c[1] == d[1]
        if horizontal_a == horizontal_b:
            fixed = 1 if horizontal_a else 0; moving = 1-fixed
            if a[fixed] != c[fixed]:
                return None
            low=max(min(a[moving],b[moving]),min(c[moving],d[moving])); high=min(max(a[moving],b[moving]),max(c[moving],d[moving]))
            if low > high:
                return None
            if low < high:
                return 'overlap'
            return [low,a[1]] if horizontal_a else [a[0],low]
        if not horizontal_a:
            return intersection(c,d,a,b)
        if min(a[0],b[0]) <= c[0] <= max(a[0],b[0]) and min(c[1],d[1]) <= a[1] <= max(c[1],d[1]):
            return [c[0],a[1]]
        return None

    def endpoint_node(r, p):
        if r['points'][0] == p:
            return r['source']
        if r['points'][-1] == p:
            return r['target']
        return None

    for i, (aid, ai, a, b) in enumerate(segments):
        for bid, bi, c, d in segments[i+1:]:
            if aid == bid and abs(ai-bi) <= 1:
                continue
            hit=intersection(a,b,c,d)
            if hit is None:
                continue
            shared = hit != 'overlap' and endpoint_node(routes[aid], hit) is not None and endpoint_node(routes[aid], hit) == endpoint_node(routes[bid], hit)
            need(shared, aid + ' intersects or overlaps ' + bid + '; use separate channels or an explicit junction node')

    array(data.get('legend', []), 'legend')
    for item in data.get('legend', []):
        need(isinstance(item, dict), 'legend item must be an object'); text(item.get('label'), 'legend.label')
        need(item.get('color') in COLORS, 'unknown legend color')
    array(data.get('steps'), 'steps', True)
    for s in data['steps']:
        need(isinstance(s, dict), 'step must be an object')
        ident(s.get('id'), 'step.id'); need(s['id'] not in steps, 'duplicate step'); steps.add(s['id'])
        number(s.get('duration'), 'step.duration'); need(s['duration'] > 0, 'duration must be positive')
        text(s.get('label'), 'step.label', True)
        for key in ('description', 'shortLabel'):
            if key in s:
                text(s[key], 'step.' + key)
        for key, valid_ids in (('activeNodes', nodes), ('activeRoutes', routes)):
            array(s.get(key, []), key)
            need(all(isinstance(value, str) and value in valid_ids for value in s.get(key, [])), key + ': unknown identifier')
        states = s.get('nodeStates', {}); need(isinstance(states, dict), 'nodeStates must be an object')
        for nid, state in states.items():
            need(nid in nodes and isinstance(state, dict), 'unknown nodeStates node')
            for key in ('state','operation','footer'):
                if key in state:
                    text(state[key], 'nodeStates.' + key)
            if 'tone' in state:
                need(state['tone'] in COLORS, 'unknown state tone')
            meter_ids = {m['id'] for m in nodes[nid].get('meters', [])}
            if 'selectedMeter' in state:
                need(state['selectedMeter'] is None or state['selectedMeter'] in meter_ids, 'unknown selectedMeter')
            values=state.get('meterValues', {}); need(isinstance(values, dict), 'meterValues must be an object')
            for mid, value in values.items():
                need(mid in meter_ids, 'unknown meterValues key'); number(value, 'meterValues', 0, 1)
        labels = s.get('routeLabels', {}); need(isinstance(labels, dict), 'routeLabels must be an object')
        for rid, label in labels.items():
            need(rid in routes and 'label' in routes[rid], 'routeLabels requires a route with label'); text(label, 'routeLabels')
    return {'nodes': len(nodes), 'routes': len(routes), 'steps': len(steps), 'duration': sum(s['duration'] for s in data['steps'])}

