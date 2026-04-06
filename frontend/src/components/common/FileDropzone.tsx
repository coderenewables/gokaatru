import { useRef } from "react";

type FileDropzoneProps = {
  label: string;
  helperText: string;
  accept?: string;
  disabled?: boolean;
  onSelect: (file: File) => void;
};

export function FileDropzone({ label, helperText, accept, disabled = false, onSelect }: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  function handleFiles(fileList: FileList | null) {
    const file = fileList?.item(0);
    if (!file) {
      return;
    }
    onSelect(file);
  }

  return (
    <div
      className={disabled ? "file-dropzone file-dropzone-disabled" : "file-dropzone"}
      onClick={() => {
        if (!disabled) {
          inputRef.current?.click();
        }
      }}
      onDragOver={(event) => {
        event.preventDefault();
      }}
      onDrop={(event) => {
        event.preventDefault();
        if (!disabled) {
          handleFiles(event.dataTransfer.files);
        }
      }}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(event) => {
        if ((event.key === "Enter" || event.key === " ") && !disabled) {
          event.preventDefault();
          inputRef.current?.click();
        }
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        disabled={disabled}
        onChange={(event) => handleFiles(event.target.files)}
      />
      <strong>{label}</strong>
      <p>{helperText}</p>
      <span className="file-dropzone-action">Choose file or drop here</span>
    </div>
  );
}