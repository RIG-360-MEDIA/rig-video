// Our own map maker: a country highlighted, places marked and labelled. No routes or lines (NDC/DNL rule).
import { useEffect, useMemo, useRef, useState } from "react";
import { geoMercator, geoPath, geoCentroid, type GeoPermissibleObjects } from "d3-geo";
import { MapPin, Plus, X } from "@phosphor-icons/react";
import { Button, IconButton, Input, cx } from "./ui";
import { findPlaces, type Place } from "@/data/store";

type Feature = { type: "Feature"; properties: { name: string; iso: string }; geometry: GeoPermissibleObjects };
let cache: Feature[] | null = null;
async function countries(): Promise<Feature[]> {
  if (!cache) cache = (await (await fetch("/geo/countries.geojson")).json()).features;
  return cache!;
}

/** Label boxes beside each marker: right, else left, else stepped down, so close places (Brooklyn, New York City) don't cover each other. */
export function labels(pts: [number, number][], widths: number[]) {
  const out: { x: number; y: number; lx: number; ly: number; w: number }[] = [];
  const hits = (lx: number, ly: number, w: number) => out.some((o) => lx < o.lx + o.w && o.lx < lx + w && ly < o.ly + 30 && o.ly < ly + 30);
  pts.forEach(([x, y], i) => {
    const w = widths[i];
    const tries = [0, 1, 2, 3].flatMap((k) => [[x + 12, y - 16 + k * 34], [x - 12 - w, y - 16 + k * 34]]);
    const [lx, ly] = tries.find(([a, b]) => !hits(a, b, w)) ?? tries[0];
    out.push({ x, y, lx, ly, w });
  });
  return out;
}

export function MapMaker({ suggest, onAdd }: { suggest: string; onAdd: (m: { src: string; title: string }) => void }) {
  const [feats, setFeats] = useState<Feature[]>([]);
  const [marks, setMarks] = useState<Place[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Place[]>([]);
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => { void countries().then(setFeats); }, []);
  useEffect(() => { void findPlaces({ text: suggest }).then(setMarks); }, [suggest]);
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    const t = setTimeout(() => void findPlaces({ q: q.trim() }).then((h) => setHits(h.filter((x) => !marks.some((m) => m.name === x.name && m.iso === x.iso)))), 200);
    return () => clearTimeout(t);
  }, [q, marks]);

  const W = 960; const H = 540;
  const focus = useMemo(() => {
    const iso = marks[0]?.iso;
    return feats.find((f) => f.properties.iso === iso);
  }, [feats, marks]);
  const proj = useMemo(() => {
    const pts = { type: "MultiPoint", coordinates: marks.map((m) => [m.lon, m.lat]) } as GeoPermissibleObjects;
    const p = geoMercator();
    const lon = marks.map((m) => m.lon); const lat = marks.map((m) => m.lat);
    const span = marks.length ? Math.max(Math.max(...lon) - Math.min(...lon), (Math.max(...lat) - Math.min(...lat)) * 1.6, 14) : 120;
    const c = marks.length ? geoCentroid(pts) : [0, 20];
    return p.center(c as [number, number]).scale((W / (span * 2.6)) * 57).translate([W / 2, H / 2]);
  }, [marks]);
  const path = geoPath(proj);

  function save() {
    const el = svg.current!; const xml = new XMLSerializer().serializeToString(el);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas"); c.width = 1280; c.height = 720;
      c.getContext("2d")!.drawImage(img, 0, 0, 1280, 720);
      onAdd({ src: c.toDataURL("image/jpeg", 0.9), title: `Map: ${marks.map((m) => m.name).join(", ")}` });
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="overflow-hidden rounded-[2px] ring-1 ring-g4">
        <svg ref={svg} viewBox={`0 0 ${W} ${H}`} xmlns="http://www.w3.org/2000/svg" className="block w-full">
          <rect width={W} height={H} fill="#0d1a24" />
          {feats.map((f, i) => (
            <path key={i} d={path(f.geometry) ?? ""} fill={f === focus ? "#3b4a58" : "#1f2a33"} stroke="#0d1a24" strokeWidth={0.8} />
          ))}
          {focus && <text x={(path.centroid(focus.geometry)[0])} y={(path.centroid(focus.geometry)[1]) + 60} fill="#8aa0b3" fontFamily="Archivo Variable, Arial" fontSize="22" fontWeight="700" letterSpacing="6" textAnchor="middle">{focus.properties.name.toUpperCase()}</text>}
          {labels(marks.map((m) => proj([m.lon, m.lat]) ?? [0, 0]), marks.map((m) => m.name.length * 11.5 + 18)).map(({ x, y, lx, ly, w }, i) => (
            <g key={marks[i].name + marks[i].iso}>
              <circle cx={x} cy={y} r={16} fill="#e31b23" opacity={0.18} />
              <circle cx={x} cy={y} r={6.5} fill="#e31b23" stroke="#fff" strokeWidth={2} />
              <rect x={lx} y={ly} width={w} height={30} fill="#0a0b0d" opacity={0.86} />
              <text x={lx + 9} y={ly + 21} fill="#fff" fontFamily="Archivo Variable, Arial" fontSize="18" fontWeight="700">{marks[i].name}</text>
            </g>
          ))}
        </svg>
      </div>
      <div className="flex flex-col gap-3">
        <div className="text-[13px] font-semibold">Places on the map</div>
        <ul className="space-y-1.5">
          {marks.map((m) => (
            <li key={m.name + m.iso} className="flex items-center gap-2 rounded-sm border border-g4 bg-g2 py-1 pr-1 pl-2.5 text-[13px]">
              <MapPin size={14} weight="fill" className="text-marker" />{m.name}<span className="ml-auto font-mono text-[10.5px] text-g8">{m.iso}</span>
              <IconButton label={`Remove ${m.name}`} size="sm" onClick={() => setMarks(marks.filter((x) => x !== m))}><X size={12} /></IconButton>
            </li>
          ))}
        </ul>
        <div className="relative">
          <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && hits[0]) { setMarks([...marks, hits[0]]); setQ(""); } }} placeholder="Add a place" aria-label="Add a place" />
          {hits.length > 0 && (
            <ul className="absolute inset-x-0 top-10 z-10 rounded-sm border border-g5 bg-g2 p-1 shadow-xl">
              {hits.map((h) => <li key={h.name + h.iso + h.lat}><button className="flex w-full items-center gap-2 rounded-xs px-2 py-1.5 text-left text-[13px] hover:bg-g4" onClick={() => { setMarks([...marks, h]); setQ(""); }}><Plus size={12} />{h.name}<span className="ml-auto font-mono text-[10.5px] text-g8">{h.iso}</span></button></li>)}
            </ul>
          )}
        </div>
        <p className={cx("text-[12px] text-g8")}>Markers and labels only. Our maps never draw routes or lines.</p>
        {!marks.length && <p className="text-[12.5px] text-g8">Add at least one place.</p>}
        <Button kind="primary" className="mt-auto" disabled={!marks.length} onClick={save}>Add this map</Button>
      </div>
    </div>
  );
}
