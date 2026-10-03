// Domain kit shared by the item panel, Actividad and the task views (phase 3). See ./README.md.

// Process reasoning
export { ProcessMap, type ProcessMapProps } from './ProcessMap'
export { processFlow, findFlowFilter, flowIssues, type ProcessFlow, type FlowNode, type FlowLeaf, type FlowLink, type FlowFilter } from './processFlow'
export { useProcessFlow } from './useProcessFlow'
export { layoutFlow, type FlowLayout } from './flowLayout'

// Item reasoning
export { ReasoningView, type ReasoningViewProps } from './ReasoningView'
export { PolicyCascade, type PolicyCascadeProps } from './PolicyCascade'
export { TraceTimeline, ModelChip, type TraceTimelineProps } from './TraceTimeline'
export {
  apCascade,
  reasoningSteps,
  reasoningSummary,
  bankMatchDetail,
  loanInterest,
  matchShape,
  type CascadeCheck,
  type ReasoningStep,
  type ReasoningSummary,
  type ReasoningFact,
} from './reasoning'
export { BankMatchFacts } from './BankMatchFacts'

// Entries, evidence, masters, golden
export { JournalEntryView, type JournalEntryViewProps } from './JournalEntryView'
export { journalTotals, type JournalTotals } from './journal'
export { EvidenceList, EvidenceBody, ErpRecord, BookLine, type EvidenceEntry, type EvidenceListProps, type EvidenceKind } from './EvidenceList'
export { DocumentViewer, EmailView, EInvoiceView, prettyXml, type DocumentViewerProps } from './DocumentViewer'
export { JsonView, type JsonViewProps } from './JsonView'
export { MasterCompare, ApMasterCompare, apMasterRows, compareState, type CompareRow, type MasterCompareProps } from './MasterCompare'
export { RawBankRecord, type RawBankRecordProps } from './RawBankRecord'
export { GoldenDiff, diffLabel, type GoldenDiffProps } from './GoldenDiff'
export { findErpRecord, findStatementLine, parseBookLine, uniqueRefs } from './evidence'

// Context and labels
export { useItemContext, itemRows, type ItemContext, type ItemContextState } from './useItemContext'
export { TASK_META, EVENT_KIND_META, BILLING_TYPE_LABELS, itemTaskHref, evidenceKey, evidenceLabel, erpFileLabel, type TaskMeta } from './labels'
export { itemEurCents } from './fx'
export { useAsync, type AsyncState } from './useAsync'
