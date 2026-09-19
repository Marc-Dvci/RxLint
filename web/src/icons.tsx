type P = { className?: string };
const s = { width: 18, height: 18, fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export const Logo = () => (
  <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
    <rect width="32" height="32" rx="8" fill="var(--brand)" />
    <path d="M9 8h7.5a4.5 4.5 0 0 1 0 9H9zM9 17v7M14 17l7 7" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="23.5" cy="10" r="2.2" fill="#7de3c4" />
  </svg>
);
export const IScan = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2M7 12h10" /></svg>);
export const IBook = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 21V5M8 7h7M8 11h7" /></svg>);
export const IChart = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M4 20h16M7 16v-5M12 16V6M17 16v-8" /></svg>);
export const ILayers = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="m12 3 9 5-9 5-9-5zM3 13l9 5 9-5" /></svg>);
export const IRx = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M6 20V4h6a4 4 0 0 1 0 8H6M11 12l8 8M19 12l-8 8" /></svg>);
export const IBottle = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M9 2h6v3H9zM8 5h8l1 3v12a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V8zM7 11h10v6H7" /></svg>);
export const IUser = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></svg>);
export const IAlert = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M12 3 2 20h20zM12 10v4M12 17.5v.5" /></svg>);
export const ICheck = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="m5 12 5 5 9-10" /></svg>);
export const IQuestion = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.5" /></svg>);
export const IScope = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><circle cx="12" cy="12" r="9" /><path d="M5.6 5.6l12.8 12.8" /></svg>);
export const IGlobe = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></svg>);
export const IFile = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M14 3H6v18h12V7zM14 3v4h4M9 13h6M9 17h6" /></svg>);
export const IDown = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg>);
export const IChevron = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="m9 6 6 6-6 6" /></svg>);
export const IExternal = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>);
export const IMic = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>);
export const IShield = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z" /></svg>);
export const IRefresh = (p: P) => (<svg viewBox="0 0 24 24" {...s} {...p}><path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6" /></svg>);

export function StateIcon({ state }: { state: string }) {
  if (state === "PASS") return <ICheck />;
  if (state === "REVIEW") return <IAlert />;
  if (state === "CANNOT_VERIFY") return <IQuestion />;
  return <IScope />;
}
