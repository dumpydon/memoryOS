export type DotCloud = {
  width: number;
  height: number;
  step: number;
  size: number;
  count: number;
  positions: Float32Array;
  cells: Uint16Array;
  staticNoise: Float32Array;
  colorNoise: Float32Array;
};

function hash(x: number, y: number) {
  const value = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return value - Math.floor(value);
}

function fontFamily() {
  return (
    getComputedStyle(document.documentElement)
      .getPropertyValue("--font-wordmark")
      .trim() || 'ui-monospace, "SFMono-Regular", Menlo, monospace'
  );
}

/** Rasterize the wordmark once and retain only cells inside its glyph mask. */
export function createDotCloud(
  width: number,
  height: number,
  label: string,
): DotCloud {
  const mask = document.createElement("canvas");
  mask.width = Math.max(1, Math.round(width));
  mask.height = Math.max(1, Math.round(height));
  const context = mask.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Canvas 2D context is unavailable");

  const maxWidth = width * 0.88;
  let fontSize = Math.min(height * 0.58, 190);
  context.font = `650 ${fontSize}px ${fontFamily()}`;
  let metrics = context.measureText(label);
  if (metrics.width > maxWidth) fontSize *= maxWidth / metrics.width;
  context.font = `650 ${fontSize}px ${fontFamily()}`;
  metrics = context.measureText(label);
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.fillStyle = "#ffffff";
  context.fillText(
    label,
    (width - metrics.width) / 2,
    height / 2 + fontSize * 0.02,
  );

  const pixels = context.getImageData(0, 0, mask.width, mask.height).data;
  const size = 3;
  const step = 4;
  const columns = Math.floor((width + 1) / step);
  const rows = Math.floor((height + 1) / step);
  const gridWidth = columns > 0 ? columns * size + (columns - 1) : 0;
  const gridHeight = rows > 0 ? rows * size + (rows - 1) : 0;
  const offsetX = Math.round((width - gridWidth) / 2);
  const offsetY = Math.round((height - gridHeight) / 2);
  const positions: number[] = [];
  const cells: number[] = [];
  const staticNoise: number[] = [];
  const colorNoise: number[] = [];

  for (let row = 0; row < rows; row += 1) {
    const y = offsetY + row * step;
    for (let column = 0; column < columns; column += 1) {
      const x = offsetX + column * step;
      const pixelX = Math.min(mask.width - 1, Math.round(x + size / 2));
      const pixelY = Math.min(mask.height - 1, Math.round(y + size / 2));
      if (pixels[(pixelY * mask.width + pixelX) * 4 + 3] < 96) continue;
      positions.push(x, y);
      cells.push(column, row);
      staticNoise.push(hash(column, row));
      colorNoise.push(hash(column + 73, row + 157));
    }
  }

  return {
    width,
    height,
    step,
    size,
    count: staticNoise.length,
    positions: Float32Array.from(positions),
    cells: Uint16Array.from(cells),
    staticNoise: Float32Array.from(staticNoise),
    colorNoise: Float32Array.from(colorNoise),
  };
}
