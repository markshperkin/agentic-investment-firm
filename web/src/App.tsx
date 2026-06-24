import { useState } from "react";
import EventFeed from "./views/EventFeed";
import Portfolio from "./views/Portfolio";

type Tab = "feed" | "portfolio";

export default function App() {
  const [tab, setTab] = useState<Tab>("feed");
  return (
    <div style={{ fontFamily: "system-ui", padding: 16 }}>
      <header style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
        <strong>Agentic Investment Firm</strong>
        <nav style={{ display: "flex", gap: 8 }}>
          <TabButton active={tab === "feed"} onClick={() => setTab("feed")}>
            Event Feed
          </TabButton>
          <TabButton active={tab === "portfolio"} onClick={() => setTab("portfolio")}>
            Portfolio
          </TabButton>
        </nav>
      </header>
      {tab === "feed" ? <EventFeed /> : <Portfolio />}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        border: "none",
        borderBottom: active ? "2px solid #333" : "2px solid transparent",
        background: "none",
        cursor: "pointer",
        fontWeight: active ? 600 : 400,
        padding: "4px 8px",
      }}
    >
      {children}
    </button>
  );
}
