import { useEffect, useState } from "react";
import { api, type Health } from "./api";
import { IBook, IChart, ILayers, IScan, Logo } from "./icons";
import Verify from "./pages/Verify";
import CaseView from "./pages/CaseView";
import RulePack from "./pages/RulePack";
import Bench from "./pages/Bench";
import About from "./pages/About";

function useRoute(): string {
  const [hash, setHash] = useState(() => window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.slice(1);
}

function providerLabel(p: string): string {
  if (p === "nebius-token-factory") return "Token Factory";
  if (p === "local-llama.cpp") return "local llama.cpp";
  return p;
}

function ModelChips({ health }: { health: Health | null }) {
  if (!health) return <span className="chip"><span className="spinner" /> connecting</span>;
  const omni = health.models.omni;
  const ultra = health.models.ultra;
  const replayNote = health.model_mode === "replay" ? " · replay" : health.model_mode === "auto" ? "" : "";
  return (
    <>
      <span className="chip nv" title={omni.model}>
        <span className={`dot ${omni.configured ? "ok" : "warn"}`} />
        <b>Nemotron 3 Nano Omni</b> {omni.configured ? providerLabel(omni.provider) : "recorded responses"}{replayNote}
      </span>
      <span className="chip nv" title={ultra.model}>
        <span className={`dot ${ultra.configured ? "ok" : "off"}`} />
        <b>Nemotron 3 Ultra</b> {ultra.configured ? providerLabel(ultra.provider) : "deterministic fallback"}
      </span>
      <span className="chip" title="Tavily Search + Extract over allowlisted regulator domains">
        <span className={`dot ${health.tavily.configured ? "ok" : "off"}`} />
        Tavily {health.tavily.configured ? "live" : "not configured"}
      </span>
    </>
  );
}

export default function App() {
  const route = useRoute();
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  let page = <Verify />;
  let key = "verify";
  const m = route.match(/^\/case\/([\w-]+)/);
  if (m) {
    page = <CaseView id={m[1]} health={health} />;
    key = "verify";
  } else if (route.startsWith("/rules")) {
    page = <RulePack />;
    key = "rules";
  } else if (route.startsWith("/bench")) {
    page = <Bench />;
    key = "bench";
  } else if (route.startsWith("/about")) {
    page = <About />;
    key = "about";
  }

  return (
    <div className="shell">
      <aside className="side">
        <a className="brand" href="#/" style={{ textDecoration: "none", color: "inherit" }}>
          <Logo />
          <div>
            <div className="word">RxLint</div>
            <div className="tag">Static analysis for<br />medication dispensing</div>
          </div>
        </a>
        <nav className="nav">
          <a href="#/" className={key === "verify" ? "on" : ""}><IScan /> Verify</a>
          <a href="#/rules" className={key === "rules" ? "on" : ""}><IBook /> Rule pack</a>
          <a href="#/bench" className={key === "bench" ? "on" : ""}><IChart /> Benchmark</a>
          <a href="#/about" className={key === "about" ? "on" : ""}><ILayers /> How it works</a>
        </nav>
        <div className="foot">
          {health && (
            <div>
              <div className="upper" style={{ marginBottom: 4 }}>Installed pack</div>
              <div style={{ color: "var(--ink-2)" }}>{health.rulepack.title} {health.rulepack.version}</div>
              <div className="mono tiny" title={health.rulepack.sha256}>sha256 {health.rulepack.sha256.slice(0, 12)}</div>
              <div>{health.rulepack.rules} rules</div>
            </div>
          )}
          <div>Research prototype. Not for clinical use.</div>
        </div>
      </aside>
      <main className="main">
        <div className="topbar">
          <ModelChips health={health} />
          <span className="grow" />
          <span className="chip">NVIDIA Nemotron · Nebius Token Factory</span>
        </div>
        {page}
      </main>
    </div>
  );
}
