import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Search } from "lucide-react";

export interface Command {
  id: string;
  label: string;
  group: string;
  hint?: string;
  keywords?: string;
  icon?: ReactNode;
  run: () => void;
}

export function CommandPalette({
  open,
  commands,
  onClose,
}: {
  open: boolean;
  commands: Command[];
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const baseId = useId().replace(/:/g, "");

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) {
      setQuery("");
      setActive(0);
      node.showModal();
      requestAnimationFrame(() => input.current?.focus());
    }
    if (!open && node.open) node.close();
  }, [open]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((command) =>
      [command.label, command.group, command.keywords ?? "", command.hint ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [commands, query]);

  const grouped = useMemo(() => {
    const groups = new Map<string, Command[]>();
    for (const command of filtered) {
      const list = groups.get(command.group) ?? [];
      list.push(command);
      groups.set(command.group, list);
    }
    return Array.from(groups.entries());
  }, [filtered]);

  const run = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    command.run();
  };

  const boundedActive = Math.min(active, Math.max(0, filtered.length - 1));
  const activeCommand = filtered[boundedActive];

  return (
    <dialog
      ref={dialog}
      className="command-palette"
      aria-label="命令面板"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setActive((value) =>
            filtered.length ? (value + 1) % filtered.length : 0,
          );
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          setActive((value) =>
            filtered.length
              ? (value - 1 + filtered.length) % filtered.length
              : 0,
          );
        } else if (event.key === "Enter") {
          event.preventDefault();
          run(activeCommand);
        }
      }}
    >
      <div className="command-search">
        <Search size={17} aria-hidden="true" />
        <input
          ref={input}
          value={query}
          aria-label="搜索命令"
          placeholder="搜索页面、任务或操作…"
          role="combobox"
          aria-expanded="true"
          aria-controls={`${baseId}-list`}
          aria-activedescendant={
            activeCommand ? `${baseId}-${activeCommand.id}` : undefined
          }
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
        />
        <kbd className="kbd">esc</kbd>
      </div>
      <div
        className="command-list"
        role="listbox"
        id={`${baseId}-list`}
        aria-label="可用命令"
      >
        {grouped.map(([group, items]) => (
          <section key={group} className="command-group">
            <h3>{group}</h3>
            {items.map((command) => {
              const index = filtered.indexOf(command);
              return (
                <button
                  key={command.id}
                  id={`${baseId}-${command.id}`}
                  role="option"
                  aria-selected={index === boundedActive}
                  className={`command-item ${index === boundedActive ? "active" : ""}`}
                  onMouseMove={() => setActive(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => run(command)}
                >
                  {command.icon && (
                    <span className="command-icon" aria-hidden="true">
                      {command.icon}
                    </span>
                  )}
                  <span>{command.label}</span>
                  {command.hint && <kbd>{command.hint}</kbd>}
                </button>
              );
            })}
          </section>
        ))}
        {filtered.length === 0 && (
          <p className="command-empty">没有匹配的命令。</p>
        )}
      </div>
      <footer className="command-footer">
        <span>
          <kbd>↑</kbd>
          <kbd>↓</kbd> 选择
        </span>
        <span>
          <kbd>↵</kbd> 执行
        </span>
        <span>
          <kbd>esc</kbd> 关闭
        </span>
      </footer>
    </dialog>
  );
}
