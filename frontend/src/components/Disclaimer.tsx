// Exact wording from SPEC §2.4. Shown on every page.
export const DISCLAIMER_TITLE = "Decision-support draft, not a prediction or an order.";
export const DISCLAIMER_BODY =
  "Pravah uses simplified, uncalibrated planning models (HAND flood mapping, rational-method runoff, susceptibility indices). Results are estimates for planning and must be reviewed by qualified officials before any action.";

export default function Disclaimer() {
  return (
    <div className="disclaimer" role="note">
      <strong>{DISCLAIMER_TITLE}</strong> {DISCLAIMER_BODY}
    </div>
  );
}
