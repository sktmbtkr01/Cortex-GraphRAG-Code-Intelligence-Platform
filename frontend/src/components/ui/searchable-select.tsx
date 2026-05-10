"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";

type SearchableSelectOption = {
  value: string;
  label: string;
  meta?: string;
};

type SearchableSelectProps = {
  label: string;
  value: string;
  options: SearchableSelectOption[];
  placeholder: string;
  emptyText: string;
  disabled?: boolean;
  onChange: (value: string) => void;
};

export default function SearchableSelect({
  label,
  value,
  options,
  placeholder,
  emptyText,
  disabled,
  onChange,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const selected = options.find((option) => option.value === value);
  const filteredOptions = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return options;
    return options.filter((option) => {
      return `${option.label} ${option.meta || ""}`.toLowerCase().includes(normalizedQuery);
    });
  }, [options, query]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  return (
    <div className="searchable-select" ref={rootRef}>
      <span className="searchable-select-label">{label}</span>
      <button
        type="button"
        className="searchable-select-trigger"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={selected ? "" : "is-placeholder"}>{selected?.label || placeholder}</span>
        <ChevronDown size={16} />
      </button>

      {open && !disabled && (
        <div className="searchable-select-popover">
          <div className="searchable-select-search">
            <Search size={15} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Search ${label.toLowerCase()}...`}
              autoFocus
            />
          </div>

          <div className="searchable-select-list" role="listbox">
            {filteredOptions.length === 0 ? (
              <div className="searchable-select-empty">{emptyText}</div>
            ) : (
              filteredOptions.map((option) => (
                <button
                  type="button"
                  key={option.value}
                  className={`searchable-select-item ${option.value === value ? "active" : ""}`}
                  onClick={() => {
                    onChange(option.value);
                    setOpen(false);
                  }}
                  role="option"
                  aria-selected={option.value === value}
                >
                  <span>
                    <strong>{option.label}</strong>
                    {option.meta && <small>{option.meta}</small>}
                  </span>
                  {option.value === value && <Check size={15} />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
