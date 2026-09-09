export function PlaceholderPanel({
  title,
  items,
}: {
  title: string;
  items: string[];
}) {
  return (
    <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-6">
      <h3 className="text-sm font-medium text-zinc-300">{title}</h3>
      <ul className="mt-4 space-y-2">
        {items.map((item) => (
          <li
            key={item}
            className="flex items-center gap-2 text-sm text-zinc-500 before:h-1.5 before:w-1.5 before:rounded-full before:bg-zinc-700 before:content-['']"
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
