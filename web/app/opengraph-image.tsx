import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Dynamiq Context Engine";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    <div
      style={{
        height: "100%",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        padding: "72px",
        background:
          "linear-gradient(135deg, #0a0a0a 0%, #181818 50%, #0a0a0a 100%)",
        color: "#fafafa",
        fontFamily: "sans-serif",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          marginBottom: 36,
        }}
      >
        <div
          style={{
            width: 72,
            height: 72,
            borderRadius: 18,
            background: "#fafafa",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#0a0a0a",
            fontSize: 44,
            fontWeight: 700,
            lineHeight: 1,
            letterSpacing: "-0.04em",
          }}
        >
          D
        </div>
        <div style={{ display: "flex", fontSize: 40, fontWeight: 600 }}>
          Dynamiq
          <span style={{ opacity: 0.55, marginLeft: 16, fontWeight: 400 }}>
            Context Engine
          </span>
        </div>
      </div>
      <div
        style={{
          display: "flex",
          fontSize: 64,
          fontWeight: 600,
          lineHeight: 1.1,
          letterSpacing: "-0.03em",
          maxWidth: 960,
        }}
      >
        A memory layer your agents can actually use.
      </div>
      <div
        style={{
          display: "flex",
          marginTop: 32,
          fontSize: 28,
          lineHeight: 1.35,
          opacity: 0.7,
          maxWidth: 960,
        }}
      >
        Typed, bi-temporal knowledge graph · MCP-native · shared between you and
        every agent you connect.
      </div>
    </div>,
    { ...size },
  );
}
