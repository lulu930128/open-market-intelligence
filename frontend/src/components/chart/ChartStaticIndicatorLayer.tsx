"use client";

type OverlaySize = {
  height: number;
  width: number;
};

type CloudPolygon = {
  id: string;
  points: string;
  tone: "bullish" | "bearish";
};

type GapZone = {
  height: number;
  id: string;
  label: string;
  tone: "up" | "down";
  width: number;
  x: number;
  y: number;
};

type SupportResistanceLevel = {
  id: string;
  opacity: number;
  priceLabel: string;
  strength: number;
  tone: "support" | "resistance";
  y: number;
};

type VolumeProfileBin = {
  buyWidth: number;
  height: number;
  id: string;
  poc: boolean;
  priceLabel: string;
  sellWidth: number;
  volumeLabel: string;
  width: number;
  x: number;
  y: number;
};

type TechnicalSignal = {
  anchorY: number;
  id: string;
  label: string;
  line?: [{ x: number; y: number }, { x: number; y: number }] | null;
  priceLabel: string;
  timeLabel: string;
  tone: "bullish" | "bearish" | "neutral";
  x: number;
  y: number;
};

type ChartStaticIndicatorLayerProps = {
  cloudPolygons: CloudPolygon[];
  gapZones: GapZone[];
  overlaySize: OverlaySize;
  supportResistance: SupportResistanceLevel[];
  technicalSignals: TechnicalSignal[];
  volumeProfile: VolumeProfileBin[];
};

function signalColor(tone: TechnicalSignal["tone"]) {
  if (tone === "bullish") return "#dc2626";
  if (tone === "bearish") return "#059669";
  return "#7c3aed";
}

export default function ChartStaticIndicatorLayer({
  cloudPolygons,
  gapZones,
  overlaySize,
  supportResistance,
  technicalSignals,
  volumeProfile,
}: ChartStaticIndicatorLayerProps) {
  return (
    <>
      {cloudPolygons.map((polygon) => (
        <polygon
          key={polygon.id}
          points={polygon.points}
          fill={polygon.tone === "bullish" ? "#10b981" : "#ef4444"}
          opacity={0.1}
          pointerEvents="none"
        />
      ))}

      {gapZones.map((zone) => {
        const color = zone.tone === "up" ? "#dc2626" : "#059669";

        return (
          <g key={zone.id} pointerEvents="none">
            <rect
              x={zone.x}
              y={zone.y}
              width={zone.width}
              height={zone.height}
              fill={color}
              opacity={0.055}
            />
            <rect
              x={zone.x}
              y={zone.y}
              width={zone.width}
              height={zone.height}
              fill="none"
              stroke={color}
              strokeDasharray="4 4"
              strokeWidth={1}
              opacity={0.28}
            />
            {zone.height >= 10 ? (
              <text
                x={Math.max(8, Math.min(zone.x + 5, overlaySize.width - 118))}
                y={Math.max(12, zone.y + 11)}
                className="fill-slate-500 text-[10px] font-semibold tabular-nums"
                opacity={0.82}
              >
                {zone.label}
              </text>
            ) : null}
          </g>
        );
      })}

      {supportResistance.map((level) => {
        const color = level.tone === "resistance" ? "#dc2626" : "#059669";
        const prefix = level.tone === "resistance" ? "R" : "S";
        const label = `${prefix} ${level.priceLabel} x${level.strength}`;
        const labelX = Math.max(62, overlaySize.width - 164);
        const labelY = Math.max(14, Math.min(level.y - 6, overlaySize.height - 12));

        return (
          <g key={level.id} pointerEvents="none" opacity={level.opacity}>
            <line
              x1={56}
              y1={level.y}
              x2={Math.max(56, overlaySize.width - 74)}
              y2={level.y}
              stroke={color}
              strokeDasharray="7 5"
              strokeWidth={1.1}
            />
            <rect
              x={labelX - 5}
              y={labelY - 10}
              width={98}
              height={15}
              rx={2}
              fill="white"
              opacity={0.86}
            />
            <text
              x={labelX}
              y={labelY}
              className="text-[10px] font-bold tabular-nums"
              fill={color}
            >
              {label}
            </text>
          </g>
        );
      })}

      {volumeProfile.map((bin) => (
        <g key={bin.id} pointerEvents="none">
          <title>{`VPVR ${bin.priceLabel} · ${bin.volumeLabel}`}</title>
          <rect
            x={bin.x}
            y={bin.y}
            width={bin.width}
            height={bin.height}
            fill="#0f172a"
            opacity={bin.poc ? 0.08 : 0.035}
          />
          <rect
            x={bin.x}
            y={bin.y}
            width={bin.sellWidth}
            height={bin.height}
            fill="#059669"
            opacity={bin.poc ? 0.34 : 0.22}
          />
          <rect
            x={bin.x + bin.sellWidth}
            y={bin.y}
            width={bin.buyWidth}
            height={bin.height}
            fill="#dc2626"
            opacity={bin.poc ? 0.34 : 0.22}
          />
          {bin.poc ? (
            <>
              <line
                x1={Math.max(56, bin.x - 10)}
                y1={bin.y + bin.height / 2}
                x2={bin.x + bin.width}
                y2={bin.y + bin.height / 2}
                stroke="#0f172a"
                strokeDasharray="4 4"
                strokeWidth={1}
                opacity={0.38}
              />
              <text
                x={Math.max(62, bin.x - 68)}
                y={Math.max(12, bin.y + bin.height / 2 - 4)}
                className="fill-slate-700 text-[10px] font-bold tabular-nums"
                opacity={0.86}
              >
                POC {bin.priceLabel}
              </text>
            </>
          ) : null}
        </g>
      ))}

      {technicalSignals.map((signal) => {
        const color = signalColor(signal.tone);
        const labelWidth = Math.max(58, signal.label.length * 11 + 14);
        const preferLeft = signal.x + labelWidth + 14 > overlaySize.width - 68;
        const labelX = preferLeft ? Math.max(6, signal.x - labelWidth - 10) : signal.x + 10;
        const labelY = Math.max(12, Math.min(signal.y - 10, overlaySize.height - 22));
        const connectorX = preferLeft ? labelX + labelWidth : labelX;

        return (
          <g key={signal.id} pointerEvents="none">
            <title>{`${signal.timeLabel} ${signal.label} ${signal.priceLabel}`}</title>
            {signal.line ? (
              <line
                x1={signal.line[0].x}
                y1={signal.line[0].y}
                x2={signal.line[1].x}
                y2={signal.line[1].y}
                stroke={color}
                strokeWidth={1.4}
                strokeDasharray="5 4"
                opacity={0.64}
              />
            ) : null}
            <line
              x1={signal.x}
              y1={signal.anchorY}
              x2={connectorX}
              y2={labelY + 9}
              stroke="#94a3b8"
              strokeDasharray="3 3"
              strokeWidth={1}
              opacity={0.56}
            />
            <circle
              cx={signal.x}
              cy={signal.anchorY}
              r={3.2}
              fill={color}
              stroke="white"
              strokeWidth={1.1}
              opacity={0.92}
            />
            <rect
              x={labelX}
              y={labelY}
              width={labelWidth}
              height={18}
              rx={2}
              fill={color}
              opacity={0.92}
            />
            <text
              x={labelX + labelWidth / 2}
              y={labelY + 12.5}
              textAnchor="middle"
              className="fill-white text-[10px] font-bold"
            >
              {signal.label}
            </text>
          </g>
        );
      })}
    </>
  );
}
