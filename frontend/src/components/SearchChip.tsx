// Google Search suggestions (grounding terms: shown as Google sends them). Google's HTML carries a light and a dark
// style chosen by prefers-color-scheme, i.e. the computer's setting, so a light Pravah on a dark computer showed a black
// strip. The chips are left as sent; only which of Google's two styles applies follows Pravah's theme.
import { useMemo } from "react";
import { useIsDark } from "../theme";

export default function SearchChip({ html }: { html: string }) {
  const dark = useIsDark();
  const themed = useMemo(() => html
    .replace(/@media\s*\(prefers-color-scheme:\s*light\)/g, dark ? "@media (max-width: 0px)" : "@media all")
    .replace(/@media\s*\(prefers-color-scheme:\s*dark\)/g, dark ? "@media all" : "@media (max-width: 0px)"), [html, dark]);
  return <div className="web-entry" dangerouslySetInnerHTML={{ __html: themed }} />;
}
