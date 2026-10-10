import { useSources } from "../hooks/useBackend";

export default function SourcesPanel() {
  const sources = useSources();

  if (sources.isPending) {
    return <p className="text-sm text-muted">Checking what Quack can see in Notion…</p>;
  }

  if (sources.isError) {
    return (
      <p role="alert" className="text-sm text-danger">
        Could not load the list of Notion databases Quack can read.
      </p>
    );
  }

  return (
    <div>
      <p className="mb-2 text-sm text-muted">
        Quack can read {sources.data.sources.length} Notion databases
        {sources.data.partial ? " (list may be incomplete)" : ""}:
      </p>
      <ul className="flex flex-wrap gap-2">
        {sources.data.sources.map((source) => (
          <li
            key={source.id ?? source.name}
            className="rounded-full bg-chip px-3 py-1 text-sm font-semibold text-chip-ink"
          >
            {source.name}
          </li>
        ))}
      </ul>
    </div>
  );
}
