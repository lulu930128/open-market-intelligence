export type ChartEventMarkerTone = "success" | "warning" | "info";

export type ChartEventMarker = {
  id: string;
  eventType: string;
  time: string;
  label: string;
  title: string;
  tone: ChartEventMarkerTone;
};

export type ProjectedChartEventMarker = ChartEventMarker & {
  anchorY: number;
  labelX: number;
  x: number;
  y: number;
};

export type ChartMarkerCollisionRect = {
  height: number;
  width: number;
  x: number;
  y: number;
};

type ChartEventMarkerPlacement = {
  anchorY: number;
  labelX: number;
  rect: ChartMarkerCollisionRect;
  y: number;
};

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(value, maximum));
}

function overlapArea(
  left: ChartMarkerCollisionRect,
  right: ChartMarkerCollisionRect,
  padding: number
) {
  const width =
    Math.min(left.x + left.width + padding, right.x + right.width + padding) -
    Math.max(left.x - padding, right.x - padding);
  const height =
    Math.min(left.y + left.height + padding, right.y + right.height + padding) -
    Math.max(left.y - padding, right.y - padding);

  return Math.max(0, width) * Math.max(0, height);
}

export function chartEventMarkerLabelX({
  labelWidth,
  maximumX,
  minimumX,
  x,
}: {
  labelWidth: number;
  maximumX: number;
  minimumX: number;
  x: number;
}) {
  const gap = 8;

  if (x + gap + labelWidth <= maximumX) return x + gap;
  if (x - gap - labelWidth >= minimumX) return x - gap - labelWidth;

  return clamp(x - labelWidth / 2, minimumX, Math.max(minimumX, maximumX - labelWidth));
}

export function placeChartEventMarker({
  highY,
  labelWidth,
  lowY,
  maximumX,
  maximumY,
  minimumX,
  minimumY,
  occupied,
  x,
}: {
  highY: number;
  labelWidth: number;
  lowY: number;
  maximumX: number;
  maximumY: number;
  minimumX: number;
  minimumY: number;
  occupied: ChartMarkerCollisionRect[];
  x: number;
}): ChartEventMarkerPlacement {
  const labelHeight = 18;
  const labelX = chartEventMarkerLabelX({ x, labelWidth, minimumX, maximumX });
  const candidates: ChartEventMarkerPlacement[] = [];

  for (let lane = 0; lane < 5; lane += 1) {
    const aboveY = highY - 27 - lane * 22;
    const belowY = lowY + 9 + lane * 22;

    if (aboveY >= minimumY && aboveY + labelHeight <= maximumY) {
      candidates.push({
        anchorY: highY,
        labelX,
        rect: { x: labelX, y: aboveY, width: labelWidth, height: labelHeight },
        y: aboveY,
      });
    }
    if (belowY >= minimumY && belowY + labelHeight <= maximumY) {
      candidates.push({
        anchorY: lowY,
        labelX,
        rect: { x: labelX, y: belowY, width: labelWidth, height: labelHeight },
        y: belowY,
      });
    }
  }

  const available = candidates.find((candidate) =>
    occupied.every((rect) => overlapArea(candidate.rect, rect, 4) === 0)
  );
  if (available) return available;

  if (candidates.length > 0) {
    return candidates.reduce((best, candidate) => {
      const score = occupied.reduce(
        (total, rect) => total + overlapArea(candidate.rect, rect, 4),
        0
      );
      const bestScore = occupied.reduce(
        (total, rect) => total + overlapArea(best.rect, rect, 4),
        0
      );

      return score < bestScore ? candidate : best;
    });
  }

  const fallbackY = clamp(highY - 27, minimumY, maximumY - labelHeight);
  return {
    anchorY: highY,
    labelX,
    rect: { x: labelX, y: fallbackY, width: labelWidth, height: labelHeight },
    y: fallbackY,
  };
}
