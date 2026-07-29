import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function IconBase({
  children,
  ...props
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="20"
      viewBox="0 0 24 24"
      width="20"
      {...props}
    >
      {children}
    </svg>
  );
}

const strokeProps = {
  stroke: "currentColor",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  strokeWidth: 1.8,
};

export function HomeIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m3 11 9-8 9 8" {...strokeProps} />
      <path d="M5 10v10h14V10M9 20v-6h6v6" {...strokeProps} />
    </IconBase>
  );
}

export function TagIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M20 13 13 20 4 11V4h7l9 9Z" {...strokeProps} />
      <path d="M8.5 8.5h.01" {...strokeProps} />
    </IconBase>
  );
}

export function BoxIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m4 7 8-4 8 4-8 4-8-4Z" {...strokeProps} />
      <path d="M4 7v10l8 4 8-4V7M12 11v10" {...strokeProps} />
    </IconBase>
  );
}

export function StoreIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 10v10h16V10M3 4h18l-2 6H5L3 4Z" {...strokeProps} />
      <path d="M8 20v-6h4v6" {...strokeProps} />
    </IconBase>
  );
}

export function RadarIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="12" cy="12" r="8.5" {...strokeProps} />
      <circle cx="12" cy="12" r="3.5" {...strokeProps} />
      <path d="m12 12 6-6M16.5 6H18v1.5" {...strokeProps} />
    </IconBase>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="12" cy="12" r="3" {...strokeProps} />
      <path
        d="M19 14.5a1.7 1.7 0 0 0 .34 1.88l.05.05-2 2-.05-.05a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1 1.56V20h-2.9v-.4a1.7 1.7 0 0 0-1-1.56 1.7 1.7 0 0 0-1.88.34l-.05.05-2-2 .05-.05A1.7 1.7 0 0 0 7 14.5a1.7 1.7 0 0 0-1.56-1H5v-2.9h.44A1.7 1.7 0 0 0 7 9a1.7 1.7 0 0 0-.34-1.88l-.05-.05 2-2 .05.05A1.7 1.7 0 0 0 10.54 5a1.7 1.7 0 0 0 1-1.56V3h2.9v.44A1.7 1.7 0 0 0 15.46 5a1.7 1.7 0 0 0 1.88-.34l.05-.05 2 2-.05.05A1.7 1.7 0 0 0 19 9c.22.63.82 1.05 1.49 1.05H21v2.9h-.51c-.67 0-1.27.42-1.49 1.05Z"
        {...strokeProps}
      />
    </IconBase>
  );
}

export function RefreshIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M20 11a8 8 0 1 0-2.34 5.66" {...strokeProps} />
      <path d="M20 5v6h-6" {...strokeProps} />
    </IconBase>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 5v14M5 12h14" {...strokeProps} />
    </IconBase>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="11" cy="11" r="7" {...strokeProps} />
      <path d="m16 16 4 4" {...strokeProps} />
    </IconBase>
  );
}

export function ExternalLinkIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M14 4h6v6M20 4l-9 9" {...strokeProps} />
      <path d="M18 13v6H5V6h6" {...strokeProps} />
    </IconBase>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m6 6 12 12M18 6 6 18" {...strokeProps} />
    </IconBase>
  );
}

export function MenuIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 7h16M4 12h16M4 17h16" {...strokeProps} />
    </IconBase>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m5 12 4 4L19 6" {...strokeProps} />
    </IconBase>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 3 2.5 20h19L12 3Z" {...strokeProps} />
      <path d="M12 9v4M12 17h.01" {...strokeProps} />
    </IconBase>
  );
}

export function PaperPlaneIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m3 11 17-8-6.5 18-3.5-7-7-3Z" {...strokeProps} />
      <path d="m10 14 4-4" {...strokeProps} />
    </IconBase>
  );
}
