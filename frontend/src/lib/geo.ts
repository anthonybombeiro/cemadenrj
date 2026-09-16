/** Conversão simples de GeoJSON (lon/lat) para path SVG — sem depender de
 * lib de projeção cartográfica. O RJ é pequeno o suficiente (extensão de
 * poucos graus) pra uma projeção equirretangular simples (escala linear
 * lon→x, lat→y invertido) não distorcer visivelmente o mapa. */

export type GeoJsonFeature = {
  type: "Feature";
  properties: Record<string, string>;
  geometry: {
    type: "Polygon" | "MultiPolygon";
    coordinates: number[][][] | number[][][][];
  };
};

export type GeoJsonFeatureCollection = {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
};

export type BBox = { minLon: number; maxLon: number; minLat: number; maxLat: number };

export function computeBBox(fc: GeoJsonFeatureCollection): BBox {
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;

  const visitRing = (ring: number[][]) => {
    for (const [lon, lat] of ring) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  };

  for (const feature of fc.features) {
    const { type, coordinates } = feature.geometry;
    if (type === "Polygon") {
      (coordinates as number[][][]).forEach(visitRing);
    } else {
      (coordinates as number[][][][]).forEach((poly) => poly.forEach(visitRing));
    }
  }

  return { minLon, maxLon, minLat, maxLat };
}

/** Projeta [lon, lat] em [x, y] dentro de um viewBox `width`x`height`,
 * mantendo a proporção (sem esticar) e com uma margem em volta. */
export function makeProjector(bbox: BBox, width: number, height: number, padding = 10) {
  const lonSpan = bbox.maxLon - bbox.minLon;
  const latSpan = bbox.maxLat - bbox.minLat;
  // Correção grosseira de aspecto: 1° de longitude "encolhe" com cos(lat).
  const midLatRad = ((bbox.minLat + bbox.maxLat) / 2) * (Math.PI / 180);
  const lonScaleCorrection = Math.cos(midLatRad);

  const availW = width - 2 * padding;
  const availH = height - 2 * padding;
  const scaleX = availW / (lonSpan * lonScaleCorrection);
  const scaleY = availH / latSpan;
  const scale = Math.min(scaleX, scaleY);

  const drawnW = lonSpan * lonScaleCorrection * scale;
  const drawnH = latSpan * scale;
  const offsetX = padding + (availW - drawnW) / 2;
  const offsetY = padding + (availH - drawnH) / 2;

  return (lon: number, lat: number): [number, number] => {
    const x = offsetX + (lon - bbox.minLon) * lonScaleCorrection * scale;
    const y = offsetY + (bbox.maxLat - lat) * scale; // inverte Y (SVG cresce pra baixo)
    return [x, y];
  };
}

export function geometryToPath(
  geometry: GeoJsonFeature["geometry"],
  project: (lon: number, lat: number) => [number, number],
): string {
  const ringToPath = (ring: number[][]): string => {
    if (ring.length === 0) return "";
    const points = ring.map(([lon, lat]) => project(lon, lat));
    return `M${points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join("L")}Z`;
  };

  if (geometry.type === "Polygon") {
    return (geometry.coordinates as number[][][]).map(ringToPath).join(" ");
  }
  return (geometry.coordinates as number[][][][])
    .map((poly) => poly.map(ringToPath).join(" "))
    .join(" ");
}
