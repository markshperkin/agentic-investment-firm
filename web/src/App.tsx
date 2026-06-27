import { useState } from "react";
import ReplayList from "./components/ReplayList";
import DatasetList from "./components/DatasetList";
import ReplayDetail from "./components/ReplayDetail";
import DatasetDetail from "./components/DatasetDetail";

type NavTab = "replays" | "datasets";

export default function App() {
  const [navTab, setNavTab] = useState<NavTab>("replays");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [datasetVersion, setDatasetVersion] = useState(0);

  return (
    <div className="app">
      <aside className="sidepanel">
        <div className="brand">
          Agentic Investment Firm
          <small>replay control console</small>
        </div>
        <div className="nav-tabs">
          <button className={navTab === "replays" ? "active" : ""} onClick={() => setNavTab("replays")}>
            Replays
          </button>
          <button className={navTab === "datasets" ? "active" : ""} onClick={() => setNavTab("datasets")}>
            Datasets
          </button>
        </div>
        {navTab === "replays" ? (
          <ReplayList selectedRunId={selectedRunId} onSelect={setSelectedRunId} />
        ) : (
          <DatasetList
            selectedDate={selectedDate}
            onSelect={setSelectedDate}
            onChanged={() => setDatasetVersion((v) => v + 1)}
          />
        )}
      </aside>

      <main className="main">
        {navTab === "replays" ? (
          selectedRunId ? (
            <ReplayDetail runId={selectedRunId} />
          ) : (
            <div className="empty">Select a replay on the left, or start a new one.</div>
          )
        ) : selectedDate ? (
          <DatasetDetail key={datasetVersion} date={selectedDate} />
        ) : (
          <div className="empty">Select a dataset day on the left.</div>
        )}
      </main>
    </div>
  );
}
