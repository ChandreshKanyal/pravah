import { Icon } from "./m3";

// Exact wording from SPEC §2.4. Shown on every results surface, the advisory brief and exports.
export const DISCLAIMER_TITLE = "Decision-support draft, not a prediction or an order.";
export const DISCLAIMER_BODY =
  "Pravah uses simplified, uncalibrated planning models (HAND flood mapping, rational-method runoff, susceptibility indices). Results are estimates for planning and must be reviewed by qualified officials before any action.";

export default function Disclaimer({ card, className = "" }: { card?: boolean; className?: string }) {
  return (
    <div className={`banner ${card ? "card" : ""} ${className}`} role="note">
      <Icon name="info" />
      <span><b>{DISCLAIMER_TITLE}</b> {DISCLAIMER_BODY}</span>
    </div>
  );
}
