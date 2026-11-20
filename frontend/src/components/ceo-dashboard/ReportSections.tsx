import { useId, useState, type ReactNode } from "react";
import { Archive, Boxes, ChevronDown, PackageCheck, Scissors, Shirt, Truck } from "lucide-react";
import { type DashboardCopy } from "./messages";
import {
  countTotals, factoryCodes, stageKeys, stageTotals, type ActivityBucket, type BalanceBucket,
  type CeoReport, type DateRange, type Factory, type Output, type PieceCounts,
} from "./report";
import { ProductionChart } from "./ProductionChart";
import styles from "./dashboard.module.css";

export type ReportFormatting = {
  count: (value: number | string) => string;
  range: (range: DateRange) => string;
  axis: (date: string) => string;
  timestamp: (stamp: string) => string;
  duration: (minutes: number) => string;
};

type CopyAndFormat = { copy: DashboardCopy; format: ReportFormatting };
const stageStyle = { cutting: styles.cutting, printing: styles.printing, sewing: styles.sewing, packaging: styles.packaging };

function departmentName(code: string, copy: DashboardCopy) {
  switch (code) {
    case "CUT": return `${copy.MIL} · ${copy.cutting}`;
    case "ECT": return `${copy.ECO} · ${copy.cutting}`;
    case "PRT": return copy.printing;
    case "SEW": return copy.sewing;
    case "MIL": case "BST": case "ECO": return `${copy[code]} · ${copy.sewing}`;
    case "PKG": return `${copy.MIL} · ${copy.packaging}`;
    case "BPK": return `${copy.BST} · ${copy.packaging}`;
    case "ECP": return `${copy.ECO} · ${copy.packaging}`;
    case "FGS": return copy.finishedWarehouse;
    case "STR": return copy.warehouse;
    case "UNASSIGNED": return copy.UNASSIGNED;
    default: return code;
  }
}

function Metric({ value, label, unit }: { value: string; label: ReactNode; unit?: string }) {
  return <div className={styles.metric}>
    <dt>{label}</dt>
    <dd>{value}{unit && <span className={styles.metricUnit}>{unit}</span>}</dd>
  </div>;
}

function Panel({ title, description, icon, children, className, anchor }: {
  title: string; description: string; icon?: ReactNode; children: ReactNode; className?: string; anchor?: string;
}) {
  const id = useId();
  return <section id={anchor} tabIndex={anchor ? -1 : undefined}
    className={`${styles.panel}${className ? ` ${className}` : ""}`} aria-labelledby={id}>
    <header className={styles.panelHeader}>
      {icon && <span className={styles.panelIcon}>{icon}</span>}
      <div><h3 id={id}>{title}</h3><p>{description}</p></div>
    </header>
    {children}
  </section>;
}

function Details({ label, children, initiallyOpen }: { label: string; children: ReactNode; initiallyOpen?: boolean }) {
  return <details className={styles.details} open={initiallyOpen}>
    <summary>{label}<ChevronDown size={16} aria-hidden="true" /></summary>
    {children}
  </details>;
}

function DataTable({ label, headings, rows }: { label: string; headings: string[]; rows: ReactNode[][] }) {
  return <div className={styles.tableWrap} role="region" aria-label={label} tabIndex={0}>
    <table aria-label={label} className={styles.table}>
      <thead><tr>{headings.map((heading, index) => <th key={index} scope="col">{heading}</th>)}</tr></thead>
      <tbody>{rows.map(([first, ...cells], row) => <tr key={row}>
        <th scope="row">{first}</th>
        {cells.map((cell, column) => <td key={column}>{cell}</td>)}
      </tr>)}</tbody>
    </table>
  </div>;
}

function FactoryComparison({ output, factory, copy, format }: CopyAndFormat & { output: Output[]; factory: Factory }) {
  const totals = factoryCodes.map(code => ({ code, pieces: stageTotals(output.filter(row => row.factory === code)) }));
  const unattributed = stageTotals(output.filter(row => row.factory === "UNASSIGNED" || row.factory === "SHARED"));
  return <Panel title={copy.comparison} description={copy.comparisonHint} className={styles.factoryPanel}>
    <DataTable label={copy.comparison} headings={[copy.stage, ...totals.map(({ code }) => copy[code])]}
      rows={stageKeys.map(stage => {
        const max = Math.max(1, ...totals.map(({ pieces }) => pieces[stage]));
        return [copy[stage], ...totals.map(({ code, pieces }) => <div key={code} className={styles.factoryCell} data-selected={code === factory}>
          {format.count(pieces[stage])}
          <div className={`${styles.bar} ${stageStyle[stage]}`} aria-hidden="true">
            <span style={{ width: `${pieces[stage] / max * 100}%` }} />
          </div>
        </div>)];
      })} />
    {stageKeys.some(stage => unattributed[stage] > 0) && <p className={styles.panelNote}>
      {copy.unattributed} · {stageKeys.filter(stage => unattributed[stage] > 0)
        .map(stage => `${copy[stage]} ${format.count(unattributed[stage])} ${copy.piecesShort}`).join(" · ")}
    </p>}
  </Panel>;
}

function PieceMetrics({ totals, copy, format }: CopyAndFormat & { totals: PieceCounts }) {
  return <dl className={styles.metricGrid}>
    <Metric label={copy.packs} value={format.count(totals.packs)} />
    <Metric label={copy.pieces} value={format.count(totals.pieces)} />
  </dl>;
}

function FlowCard({ kind, buckets, factory, copy, format }: CopyAndFormat & {
  kind: "finished_receipts" | "shipments"; buckets: ActivityBucket[]; factory: Factory;
}) {
  const receipt = kind === "finished_receipts";
  const title = receipt ? copy.receipts : copy.shipped;
  const chartUnit = receipt ? "pieces" : "packs";
  const max = Math.max(1, ...buckets.map(bucket => bucket[kind][chartUnit]));
  const unassigned = countTotals(buckets, receipt ? "receipts_unassigned" : "shipments_unassigned");
  const legacy = receipt ? countTotals(buckets, "legacy_imports") : undefined;
  const unassignedLabel = factory === "ALL" ? copy.unassignedIncluded : copy.unassignedExcluded;
  const counts = ({ packs, pieces }: PieceCounts) => `${copy.packs} ${format.count(packs)} · ${format.count(pieces)} ${copy.piecesShort}`;
  const showUnassigned = unassigned.packs > 0 || unassigned.pieces > 0;
  return <Panel title={title} description={receipt ? copy.receiptsHint : copy.shippedHint}
    icon={receipt ? <PackageCheck size={19} aria-hidden="true" /> : <Truck size={19} aria-hidden="true" />}>
    <PieceMetrics totals={countTotals(buckets, kind)} copy={copy} format={format} />
    {buckets.length > 1 && <figure className={styles.flowFigure}>
      <figcaption className={styles.flowCaption}>{copy[chartUnit]} · {copy.breakdown.toLocaleLowerCase()}</figcaption>
      <div className={styles.flowPlot} aria-hidden="true">
        <div className={styles.flowScale}><span>{format.count(max)}</span><span>0</span></div>
        <div className={styles.flowBars} style={{ gridTemplateColumns: `repeat(${buckets.length}, minmax(0, 1fr))` }}>
          {buckets.map(bucket => <span key={bucket.end} title={`${format.range(bucket)} · ${format.count(bucket[kind][chartUnit])}`}
            style={{ height: `${bucket[kind][chartUnit] / max * 100}%` }} />)}
        </div>
      </div>
      <div className={styles.flowDates} aria-hidden="true"><span>{format.axis(buckets[0].start)}</span><span>{format.axis(buckets.at(-1)!.end)}</span></div>
    </figure>}
    {showUnassigned || (legacy && legacy.packs > 0) ? <ul className={styles.notes}>
      {showUnassigned && <li>{unassignedLabel} · {counts(unassigned)}</li>}
      {legacy && legacy.packs > 0 && <li>{copy.legacyExcluded} · {counts(legacy)}</li>}
    </ul> : null}
    {buckets.length > 1 && <Details label={copy.breakdown}>
      <DataTable label={title} headings={[copy.interval, copy.packs, copy.pieces]}
        rows={buckets.map(bucket => [format.range(bucket), format.count(bucket[kind].packs), format.count(bucket[kind].pieces)])} />
    </Details>}
  </Panel>;
}

export function Activity({ report, copy, format }: CopyAndFormat & { report: CeoReport }) {
  const { activity: { buckets }, factory } = report;
  const output = buckets.flatMap(bucket => bucket.output);
  const inScope = (row: Output) => factory === "ALL" || row.factory === factory;
  const stages = stageTotals(output.filter(inScope));
  const receipts = countTotals(buckets, "finished_receipts");
  const shipments = countTotals(buckets, "shipments");
  const points = buckets.map(bucket => ({ start: bucket.start, end: bucket.end, values: stageTotals(bucket.output.filter(inScope)) }));
  const [selectedEnd, setSelectedEnd] = useState<string>();
  const selectedIndex = buckets.findIndex(bucket => bucket.end === selectedEnd);
  const activeIndex = selectedIndex >= 0 ? selectedIndex : buckets.length - 1;
  const selectedBucket = buckets[activeIndex];
  const breakdown = selectedBucket?.output.filter(inScope) ?? [];
  const id = useId();

  return <section className={styles.reportSection} aria-labelledby={id}>
    <div className={styles.sectionHeader}><h2 id={id}>{copy.activity}</h2><p>{copy[factory]}</p></div>
    <dl className={styles.highlights}>
      <Metric label={<><Scissors size={17} aria-hidden="true" />{copy.cutting}</>} value={format.count(stages.cutting)} unit={copy.piecesShort} />
      <Metric label={<><Shirt size={17} aria-hidden="true" />{copy.sewing}</>} value={format.count(stages.sewing)} unit={copy.piecesShort} />
      <Metric label={<><PackageCheck size={17} aria-hidden="true" />{copy.receipts}</>} value={format.count(receipts.pieces)} unit={copy.piecesShort} />
      <Metric label={<><Truck size={17} aria-hidden="true" />{copy.shipped}</>} value={format.count(shipments.packs)} unit={copy.packs} />
    </dl>

    <div className={styles.activityGrid}>
      <Panel title={copy.stageTrend} description={copy.trendHint}>
        <dl className={styles.legend}>
          {stageKeys.map(stage => <Metric key={stage} value={format.count(stages[stage])}
            label={<><span className={`${styles.swatch} ${stageStyle[stage]}`} />{copy[stage]}</>} />)}
        </dl>
        <ProductionChart points={points} activeIndex={activeIndex} onSelect={index => setSelectedEnd(points[index].end)} copy={copy} format={format} />
        {selectedBucket && buckets.length > 1 && <div className={styles.intervalDetail}>
          <label className={styles.inlineSelect}><span>{copy.point}</span>
            <select value={selectedBucket.end} onChange={event => setSelectedEnd(event.target.value)}>
              {buckets.map(bucket => <option key={bucket.end} value={bucket.end}>{format.range(bucket)}</option>)}
            </select>
          </label>
          <dl className={styles.intervalTotals}>
            {stageKeys.map(stage => <Metric key={stage} label={copy[stage]} value={format.count(points[activeIndex].values[stage])} />)}
          </dl>
        </div>}
        <Details label={copy.byDepartment} initiallyOpen>
          {breakdown.length ? <DataTable label={copy.byDepartment} headings={[copy.department, copy.stage, copy.factory, copy.pieces]}
            rows={breakdown.map(row => [departmentName(row.department, copy), copy[row.stage], copy[row.factory], format.count(row.pieces)])} /> :
            <p className={styles.empty}>{copy.noOutput}</p>}
        </Details>
      </Panel>
      <FactoryComparison output={output} factory={factory} copy={copy} format={format} />
    </div>
    <div className={styles.paired}>
      <FlowCard kind="finished_receipts" buckets={buckets} factory={factory} copy={copy} format={format} />
      <FlowCard kind="shipments" buckets={buckets} factory={factory} copy={copy} format={format} />
    </div>
  </section>;
}

export function Balances({ balances, chosen, onDateChange, factory, copy, format }: CopyAndFormat & {
  balances: BalanceBucket[]; chosen: BalanceBucket; onDateChange: (end: string) => void; factory: Factory;
}) {
  const id = useId();
  const { values, as_of: asOf, status } = chosen;
  const unitLabel = (unit: string) => unit.toUpperCase() === "UNASSIGNED" ? copy.UNASSIGNED : unit.toLowerCase() === "kg" ? copy.kg : unit;
  const warehouse = values?.warehouse;
  const materialVarieties = values?.material_varieties ?? [];
  const [materialQuery, setMaterialQuery] = useState("");
  const [materialUnit, setMaterialUnit] = useState("");
  const [materialLimit, setMaterialLimit] = useState(25);
  const selectedUnit = values?.material_totals.some(row => row.unit === materialUnit) ? materialUnit : "";
  const filteredMaterials = materialVarieties.filter(row =>
    (!selectedUnit || row.unit === selectedUnit)
    && `${row.item} ${row.sku}`.toLocaleLowerCase().includes(materialQuery.trim().toLocaleLowerCase()))
    .sort((a, b) => a.unit.localeCompare(b.unit) || Number(b.quantity) - Number(a.quantity) || a.item.localeCompare(b.item));

  return <section className={styles.reportSection} aria-labelledby={id}>
    <div className={styles.sectionHeader}>
      <div>
        <h2 id={id}>{copy.balances}</h2>
        {asOf && <p><span className={`${styles.dot} ${status === "current" ? styles.liveDot : ""}`} />
          {copy[status]} · {copy.asOf} <time dateTime={asOf}>{format.timestamp(asOf)}</time></p>}
      </div>
      <label className={styles.inlineSelect}><span>{copy.balanceDate}</span>
        <select value={chosen.end} onChange={event => onDateChange(event.target.value)}>
          {balances.map(point => <option key={point.end} value={point.end}>{format.range({ start: point.end, end: point.end })}</option>)}
        </select>
      </label>
    </div>

    <div className={styles.balanceGrid}>
      <Panel title={copy.stock} description={copy.stockHint} icon={<Archive size={19} aria-hidden="true" />}>
        {warehouse ? <>
          <PieceMetrics totals={warehouse} copy={copy} format={format} />
          {warehouse.available_pieces + warehouse.reserved_pieces > 0 && <div className={styles.stockBar} aria-hidden="true">
            <span style={{ flexGrow: warehouse.available_pieces }} />
            <span style={{ flexGrow: warehouse.reserved_pieces }} />
          </div>}
          <dl className={styles.stockMetrics}>
            <Metric label={<><span className={`${styles.swatch} ${styles.sewing}`} />{copy.available}</>} value={format.count(warehouse.available_pieces)} />
            <Metric label={<><span className={`${styles.swatch} ${styles.packaging}`} />{copy.reserved}</>} value={format.count(warehouse.reserved_pieces)} />
          </dl>
          {warehouse.by_factory.length > 0 && factory === "ALL" && <Details label={copy.byLocation}>
            <DataTable label={copy.stock} headings={[copy.factory, copy.packs, copy.pieces, copy.available, copy.reserved]}
              rows={warehouse.by_factory.map(row => [copy[row.factory], format.count(row.packs), format.count(row.pieces),
                format.count(row.available_pieces), format.count(row.reserved_pieces)])} />
          </Details>}
        </> : <p className={styles.empty}>{copy.unavailable}</p>}
        {factory !== "ALL" && <p className={styles.panelNote}>{copy.sharedOnly}</p>}
      </Panel>
    </div>

    <Panel title={copy.materials} description={copy.materialsHint} icon={<Boxes size={19} aria-hidden="true" />}>
      {values?.material_totals.length ? <>
        <DataTable label={copy.materials} headings={[copy.unit, copy.quantity, copy.batches, copy.varieties]}
          rows={values.material_totals.map(row => [unitLabel(row.unit), format.count(row.quantity),
            format.count(row.active_batches), format.count(row.varieties)])} />
        {materialVarieties.length > 0 && <>
          <div className={styles.materialTools}>
            <label className={styles.materialSearch}>{copy.searchMaterials}
              <input type="search" value={materialQuery} onChange={event => { setMaterialQuery(event.target.value); setMaterialLimit(25); }} />
            </label>
            <label className={styles.inlineSelect}><span>{copy.unit}</span>
              <select value={selectedUnit} onChange={event => { setMaterialUnit(event.target.value); setMaterialLimit(25); }}>
                <option value="">{copy.allUnits}</option>
                {values.material_totals.map(row => <option key={row.unit} value={row.unit}>{unitLabel(row.unit)}</option>)}
              </select>
            </label>
          </div>
          {filteredMaterials.length ? <DataTable label={copy.byVariety} headings={[copy.material, copy.unit, copy.quantity, copy.batches]}
            rows={filteredMaterials.slice(0, materialLimit).map(row => [<div key="name" className={styles.materialName}>
              {row.item}{row.sku && <small>{row.sku}</small>}
            </div>, unitLabel(row.unit), format.count(row.quantity), format.count(row.active_batches)])} /> :
            <p className={styles.empty}>{copy.noMatchingMaterials}</p>}
          <div className={styles.materialFooter}>
            <span>{format.count(Math.min(materialLimit, filteredMaterials.length))} / {format.count(filteredMaterials.length)}</span>
            {materialLimit < filteredMaterials.length && <button type="button" className={styles.applyButton}
              onClick={() => setMaterialLimit(limit => limit + 25)}>{copy.showMore}</button>}
          </div>
        </>}
        <Details label={copy.materialBreakdown}>
          <DataTable label={copy.materialBreakdown} headings={[copy.warehouse, copy.factory, copy.quantity, copy.batches, copy.varieties]}
            rows={values.materials.map(row => [row.warehouse === "ECO_LEDGER" ? copy.ecoLedger : row.warehouse === "UNASSIGNED" ? copy.UNASSIGNED : row.warehouse,
              copy[row.factory], `${format.count(row.quantity)} ${unitLabel(row.unit)}`,
              format.count(row.active_batches), format.count(row.varieties)])} />
        </Details>
      </> : <p className={styles.empty}>{values ? copy.noMaterials : copy.unavailable}</p>}
      {factory !== "ALL" && <p className={styles.panelNote}>{copy.sharedOnly}</p>}
    </Panel>
  </section>;
}
