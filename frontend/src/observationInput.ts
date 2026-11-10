/** Missing measurements must never become numeric zero. */
export function parseObservationValue(raw: string): number {
  if (!raw.trim()) throw new Error("Введите значение измерения. Пустое поле не означает ноль.");
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error("Введите корректное число.");
  return value;
}
