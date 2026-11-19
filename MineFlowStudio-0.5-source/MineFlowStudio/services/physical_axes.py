"""Identify continuous straight survey lines independently of Excel JOIN records."""

from collections import defaultdict
from dataclasses import replace
from math import atan2, cos, degrees, floor, hypot, radians, sin

from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree

from domain.models import Point3D

EPS = 1e-9


def main_direction(axes, config):
    if config.line_azimuth is not None:
        angle = radians(90 - config.line_azimuth)
        return cos(angle), sin(angle)
    bins = defaultdict(list)
    for axis in axes:
        if axis.contour_copy or axis.closed or axis.length is None:
            continue
        for path in axis.parts:
            for a, b in zip(path, path[1:]):
                dx, dy = b.east-a.east, b.north-a.north
                length = hypot(dx, dy)
                if length > EPS:
                    angle = atan2(dy, dx)
                    slot = int(floor((degrees(angle) % 180 + .5) % 180))
                    bins[slot].append((length, angle))
    if not bins:
        return 1., 0.
    slot = min(bins, key=lambda k: (-sum(v[0] for v in bins[k]), k))
    angle = .5 * atan2(sum(w*sin(2*a) for w,a in bins[slot]),
                       sum(w*cos(2*a) for w,a in bins[slot]))
    return cos(angle), sin(angle)


def along_line(a, b, direction, angle):
    dx, dy = b.east-a.east, b.north-a.north
    size = hypot(dx, dy)
    if size <= EPS:
        return False
    return abs(dx*direction[0]+dy*direction[1])/size >= cos(radians(angle))-1e-12


def partition_paths(paths, direction, angle):
    """Split only at existing vertices where a straight line becomes a connector."""
    output = []
    for path in paths:
        if len(path) < 2:
            output.append(("unknown", (path,)))
            continue
        role, current = None, []
        for a,b in zip(path,path[1:]):
            next_role = "line" if along_line(a,b,direction,angle) else "transition"
            if next_role != role:
                if current:
                    output.append((role,(tuple(current),)))
                role, current = next_role, [a,b]
            else:
                current.append(b)
        if current:
            output.append((role,(tuple(current),)))
    return output


def _same_line(first, second, tolerance, angle):
    # Survey portions may make a small kink at the material boundary. Use the
    # two inward tangents at a common endpoint, independent of contour cuts.
    pa,pb=first.parts[0],second.parts[0]
    for points,others in ((pa,pb),):
        for at,near in ((0,1),(-1,-2)):
            for bt,bnear in ((0,1),(-1,-2)):
                p,q=points[at],others[bt]
                if hypot(p.east-q.east,p.north-q.north)>tolerance+EPS:
                    continue
                if p.rl is not None and q.rl is not None and abs(p.rl-q.rl)>tolerance+EPS:
                    continue
                dx,dy=points[near].east-p.east,points[near].north-p.north
                ex,ey=others[bnear].east-q.east,others[bnear].north-q.north
                denom=hypot(dx,dy)*hypot(ex,ey)
                if denom>EPS*EPS and (dx*ex+dy*ey)/denom <= -cos(radians(angle))+1e-12:
                    return True
    a,b = first.parts[0][0],first.parts[0][-1]
    c,d = second.parts[0][0],second.parts[0][-1]
    dx,dy=b.east-a.east,b.north-a.north
    length=hypot(dx,dy)
    if length <= EPS:
        return False
    ux,uy=dx/length,dy/length
    # Infinite supporting lines must coincide; merely crossing is insufficient.
    if max(abs((p.east-a.east)*uy-(p.north-a.north)*ux) for p in second.parts[0]) > tolerance+EPS:
        return False
    vx,vy=d.east-c.east,d.north-c.north
    other=hypot(vx,vy)
    if other <= EPS:
        return False
    if max(abs((p.east-c.east)*vy-(p.north-c.north)*vx)/other for p in first.parts[0]) > tolerance+EPS:
        return False
    first_s=[p.east*ux+p.north*uy for p in first.parts[0]]
    second_s=[p.east*ux+p.north*uy for p in second.parts[0]]
    lo=max(min(first_s),min(second_s))
    hi=min(max(first_s),max(second_s))
    if lo > hi+tolerance+EPS:
        return False
    # Same XY at another elevation is a different physical line.
    if all(p.rl is not None for p in (a,b,c,d)):
        position=(lo+hi)/2
        def z(p,q):
            sp,sq=p.east*ux+p.north*uy,q.east*ux+q.north*uy
            return p.rl+(q.rl-p.rl)*(position-sp)/(sq-sp) if abs(sq-sp)>EPS else p.rl
        if abs(z(a,b)-z(c,d)) > tolerance+EPS:
            return False
    return True


def line_components(segments, config):
    candidates=[e for e in segments if e.line_role=="line" and e.length and not e.closed
                and not e.numbering_blocked_source]
    parents={e.id:e.id for e in candidates}
    def root(key):
        while parents[key]!=key:
            parents[key]=parents[parents[key]]
            key=parents[key]
        return key
    scopes=defaultdict(list)
    for e in candidates:
        scopes[e.horizon,e.body].append(e)
    for records in scopes.values():
        paths=[LineString([p.xy for p in e.parts[0]]) for e in records]
        tree=STRtree(paths)
        for i,e in enumerate(records):
            x0,y0,x1,y1=paths[i].bounds
            pad=config.line_tolerance+EPS
            for j in tree.query(box(x0-pad,y0-pad,x1+pad,y1+pad)):
                j=int(j)
                if j>=i or not _same_line(e,records[j],config.line_tolerance,config.line_angle):
                    continue
                left,right=root(e.id),root(records[j].id)
                parents[max(left,right)]=min(left,right)
    units=defaultdict(list)
    for e in candidates:
        units["L"+root(e.id)].append(e)
    return units


def assign_physical_numbers(axes, segments, config, order_key, name_builder, log):
    units=line_components(segments,config)
    scopes=defaultdict(list)
    anchors={}
    for key,members in units.items():
        points=[p for e in members for path in e.parts for p in path]
        z=[p.rl for p in points if p.rl is not None]
        anchor=Point3D((min(p.east for p in points)+max(p.east for p in points))/2,
                       (min(p.north for p in points)+max(p.north for p in points))/2,
                       (min(z)+max(z))/2 if z else None)
        exemplar=min(members,key=lambda e:(e.refs[0].row,e.id))
        cat=config.priority if any(e.source_category==config.priority for e in members) else None
        ranked=replace(exemplar,id=key,parts=((anchor,),),source_category=cat)
        anchors[key]=ranked
        scope=exemplar.body,exemplar.horizon if config.numbering_scope=="horizon" else ""
        scopes[scope].append(key)
    for keys in scopes.values():
        for number,key in enumerate(sorted(keys,key=lambda key:order_key(anchors[key],config)),config.first):
            for e in units[key]:
                e.number,e.number_group,e.numbers=number,key,(number,)
    # A survey record can contain several straight lines plus bends between them.
    by_axis=defaultdict(list)
    for e in segments:
        by_axis[e.axis_id].append(e)
    for axis in axes:
        parts=by_axis[axis.id]
        values=sorted({e.number for e in parts if e.number is not None})
        groups={e.number_group for e in parts if e.number is not None}
        axis.numbers=tuple(values)
        axis.number=values[0] if len(values)==1 else None
        axis.number_group=next(iter(groups)) if len(groups)==1 else ""
    lines=[e for members in units.values() for e in members]
    if lines:
        shapes=[LineString([p.xy for p in e.parts[0]]) for e in lines]
        tree=STRtree(shapes)
        for e in segments:
            if e.line_role!="transition":
                continue
            neighbors=set()
            for path in e.parts:
                for p in (path[0],path[-1]):
                    for ix in tree.query(Point(p.xy).buffer(config.line_tolerance+EPS)):
                        ix=int(ix)
                        target=lines[ix]
                        if ((target.horizon,target.body)==(e.horizon,e.body)
                                and shapes[ix].distance(Point(p.xy))<=config.line_tolerance+EPS):
                            neighbors.add(target.number)
            e.numbers=tuple(sorted(neighbors))
    name_builder(axes,segments,config,log)

