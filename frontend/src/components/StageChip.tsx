import type { StageRef } from "@/api/types";
import { cx } from "@/lib/cx";
import { stageHueClass } from "@/lib/format";

/**
 * The stage's name, in a colour derived from its code. Nothing here knows which stages
 * exist: add a stage in the admin and it renders with a stable colour of its own.
 */
export function StageChip({ stage, className }: { stage: StageRef; className?: string }) {
  return (
    <span className={cx("stage-chip", stageHueClass(stage.code), className)} title={stage.name}>
      {stage.name}
    </span>
  );
}
