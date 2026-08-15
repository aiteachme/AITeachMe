export function getMasteryDrillQuestionNumber(completedCount: number, totalCount: number): number {
  const normalizedTotal = Math.max(0, Math.floor(totalCount));
  if (normalizedTotal === 0) return 0;

  const normalizedCompleted = Math.min(
    normalizedTotal,
    Math.max(0, Math.floor(completedCount)),
  );
  return Math.min(normalizedTotal, normalizedCompleted + 1);
}
