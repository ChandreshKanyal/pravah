// Material Design 3 building blocks (Google Material 3 look and motion), styled by styles.css tokens.
import {
  createContext, useCallback, useContext, useEffect, useRef, useState, type ButtonHTMLAttributes, type CSSProperties,
  type MouseEvent, type ReactNode,
} from "react";

export function Icon({ name, fill, className = "", style, title }: { name: string; fill?: boolean; className?: string; style?: CSSProperties; title?: string }) {
  return <span className={`ms ${fill ? "fill" : ""} ${className}`} style={style} aria-hidden={title ? undefined : true} title={title}>{name}</span>;
}

/** Press ripple: spawns an expanding circle from the pointer position (M3 "ripple" state). */
export function useRipple<T extends HTMLElement>() {
  return useCallback((e: MouseEvent<T>) => {
    const el = e.currentTarget;
    const r = el.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 2.2;
    const s = document.createElement("span");
    s.className = "ripple";
    s.style.width = s.style.height = `${size}px`;
    s.style.left = `${e.clientX - r.left - size / 2}px`;
    s.style.top = `${e.clientY - r.top - size / 2}px`;
    el.appendChild(s);
    setTimeout(() => s.remove(), 600);
  }, []);
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "filled" | "tonal" | "outlined" | "text" | "elevated" | "danger"; icon?: string; iconRight?: boolean;
  block?: boolean; size?: "small" | "lg";
};

export function Button({ variant = "filled", icon, iconRight, block, size, className = "", children, onMouseDown, ...rest }: BtnProps) {
  const ripple = useRipple<HTMLButtonElement>();
  return (
    <button {...rest} className={`btn btn-${variant} sl ${block ? "block" : ""} ${size ?? ""} ${iconRight ? "icon-right" : ""} ${className}`}
      onMouseDown={(e) => { if (!rest.disabled) ripple(e); onMouseDown?.(e); }}>
      {icon && !iconRight && <Icon name={icon} />}
      {children}
      {icon && iconRight && <Icon name={icon} />}
    </button>
  );
}

export function IconButton({ icon, label, variant, small, on, className = "", fill, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: string; label: string; variant?: "tonal" | "filled"; small?: boolean; on?: boolean; fill?: boolean;
}) {
  const ripple = useRipple<HTMLButtonElement>();
  return (
    <Tip text={label} below>
      <button {...rest} aria-label={label} aria-pressed={on} className={`icon-btn sl ${variant ?? ""} ${small ? "small" : ""} ${on ? "on" : ""} ${className}`}
        onMouseDown={(e) => !rest.disabled && ripple(e)}>
        <Icon name={icon} fill={fill || on} />
      </button>
    </Tip>
  );
}

export function Fab({ icon, label, onClick, variant = "", small, extended = true, title }: {
  icon: string; label?: string; onClick?: () => void; variant?: "" | "surface" | "gemini"; small?: boolean; extended?: boolean; title?: string;
}) {
  const ripple = useRipple<HTMLButtonElement>();
  return (
    <button className={`fab sl ${variant} ${small ? "small" : ""}`} onClick={onClick} onMouseDown={ripple} aria-label={title ?? label}>
      <Icon name={icon} />{extended && label}
    </button>
  );
}

export function Chip({ label, icon, selected, onClick, onRemove, variant, small, title }: {
  label: ReactNode; icon?: string; selected?: boolean; onClick?: () => void; onRemove?: () => void; variant?: "elevated"; small?: boolean; title?: string;
}) {
  const ripple = useRipple<HTMLButtonElement>();
  if (onRemove) {
    return (
      <span className={`chip input ${small ? "small" : ""}`} title={title}>
        {icon && <Icon name={icon} />}{label}
        <button aria-label="Remove" onClick={onRemove}><Icon name="close" className="sm" /></button>
      </span>
    );
  }
  return (
    <button className={`chip sl ${selected ? "selected" : ""} ${variant ?? ""} ${small ? "small" : ""} ${onClick ? "" : "static"}`}
      aria-pressed={onClick ? !!selected : undefined} onClick={onClick} onMouseDown={(e) => onClick && ripple(e)} title={title}>
      {selected ? <Icon name="check" /> : icon ? <Icon name={icon} /> : null}{label}
    </button>
  );
}

export function Segmented<T extends string>({ value, options, onChange, block, label }: {
  value: T; options: { value: T; label: string; icon?: string }[]; onChange: (v: T) => void; block?: boolean; label: string;
}) {
  return (
    <div className={`seg ${block ? "block" : ""}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} className="sl" onClick={() => onChange(o.value)} title={o.label}>
          {value === o.value ? <Icon name="check" /> : o.icon ? <Icon name={o.icon} /> : null}
          <span className="lbl">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

export function Slider({ label, value, min, max, step = 1, unit, onChange, format, hint }: {
  label: string; value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void;
  format?: (v: number) => string; hint?: string;
}) {
  const pct = ((value - min) / (max - min || 1)) * 100;
  const show = format ? format(value) : `${value}${unit ? ` ${unit}` : ""}`;
  return (
    <label className="slider">
      <span className="head"><span className="body-m">{label}</span><span className="val">{show}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} aria-valuetext={show}
        style={{ ["--p" as any]: `${pct}%` }} onChange={(e) => onChange(Number(e.target.value))} />
      {hint && <span className="ends"><span>{hint}</span></span>}
    </label>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <span className="switch">
      <input type="checkbox" role="switch" checked={checked} disabled={disabled} aria-label={label} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" /><span className="thumb" />
    </span>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange, withIcons }: {
  value: T; tabs: { value: T; label: string; icon?: string; badge?: number | string }[]; onChange: (v: T) => void; withIcons?: boolean;
}) {
  return (
    <div className={`tabs ${withIcons ? "with-icons" : ""}`} role="tablist">
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={value === t.value} className="sl" onClick={() => onChange(t.value)}>
          {withIcons && t.icon && <Icon name={t.icon} fill={value === t.value} />}
          {t.label}
          {t.badge != null && t.badge !== 0 && <span className="badge-dot">{t.badge}</span>}
        </button>
      ))}
    </div>
  );
}

export function Tip({ text, children, below }: { text: ReactNode; children: ReactNode; below?: boolean }) {
  return <span className={`tip ${below ? "below" : ""}`}>{children}<span className="tip-body" role="tooltip">{text}</span></span>;
}

export function HelpTip({ text }: { text: string }) {
  return (
    <Tip text={text}>
      <span tabIndex={0} aria-label={text} style={{ display: "inline-flex", cursor: "help" }}><Icon name="help" className="sm" /></span>
    </Tip>
  );
}

export function Linear({ value, indeterminate }: { value?: number; indeterminate?: boolean }) {
  return (
    <div className={`lin ${indeterminate ? "indet" : ""}`} role="progressbar" aria-valuenow={indeterminate ? undefined : Math.round((value ?? 0) * 100)}
      aria-valuemin={0} aria-valuemax={100}>
      <i style={indeterminate ? undefined : { width: `${Math.round((value ?? 0) * 100)}%` }} />
    </div>
  );
}

export function Dialog({ open, title, icon, children, actions, onClose }: {
  open: boolean; title: string; icon?: string; children: ReactNode; actions: ReactNode; onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        {icon && <div className="icon-head"><Icon name={icon} className="lg" /></div>}
        <h2 style={icon ? { textAlign: "center" } : undefined}>{title}</h2>
        {children}
        <div className="actions">{actions}</div>
      </div>
    </>
  );
}

export function Field({ label, children, support, error, trail }: { label: string; children: ReactNode; support?: string; error?: boolean; trail?: string }) {
  return (
    <label className={`field ${error ? "error" : ""}`}>
      {children}
      <span className="lbl">{label}</span>
      {trail && <Icon name={trail} className="trail" />}
      {support && <span className="sup">{support}</span>}
    </label>
  );
}

/* ---------- snackbar ---------- */
type Snack = { id: number; text: string; action?: { label: string; onClick: () => void } };
const SnackCtx = createContext<(text: string, action?: Snack["action"]) => void>(() => undefined);
export const useSnackbar = () => useContext(SnackCtx);

export function SnackbarProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Snack[]>([]);
  const n = useRef(0);
  const show = useCallback((text: string, action?: Snack["action"]) => {
    const id = ++n.current;
    setItems((x) => [...x.slice(-2), { id, text, action }]);
    setTimeout(() => setItems((x) => x.filter((s) => s.id !== id)), action ? 8000 : 4500);
  }, []);
  return (
    <SnackCtx.Provider value={show}>
      {children}
      <div className="snackbar-host" aria-live="polite">
        {items.map((s) => (
          <div key={s.id} className="snackbar" role="status">
            <span className="grow">{s.text}</span>
            {s.action && <button className="btn btn-text sl" onClick={() => { s.action!.onClick(); setItems((x) => x.filter((y) => y.id !== s.id)); }}>{s.action.label}</button>}
            <button className="icon-btn small sl" aria-label="Dismiss" style={{ color: "inherit" }} onClick={() => setItems((x) => x.filter((y) => y.id !== s.id))}>
              <Icon name="close" />
            </button>
          </div>
        ))}
      </div>
    </SnackCtx.Provider>
  );
}

export const nf = (n: number | null | undefined) => (n == null ? "–" : Math.round(n).toLocaleString("en-IN"));
