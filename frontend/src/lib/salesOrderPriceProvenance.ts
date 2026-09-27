type PriceLine<T extends string | number> = { unit_price: T; price_edited: boolean };

export function copyPriceProvenance<T extends string | number>(line: PriceLine<T>): PriceLine<T> {
  return { unit_price: line.unit_price, price_edited: line.price_edited };
}

export function submittedUnitPrice(line: PriceLine<string | number>): number | null {
  return line.price_edited && line.unit_price !== "" ? Number(line.unit_price) : null;
}
