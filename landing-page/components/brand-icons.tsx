import { cn } from "@/lib/cn";

export function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg
      role="img"
      aria-label="GitHub"
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      fill="currentColor"
      className={cn("h-5 w-5", className)}
    >
      <path d="M12 .5C5.73.5.99 5.24.99 11.51c0 4.86 3.15 8.98 7.52 10.43.55.1.75-.24.75-.53 0-.26-.01-.95-.02-1.86-3.06.66-3.71-1.47-3.71-1.47-.5-1.27-1.22-1.61-1.22-1.61-1-.68.08-.67.08-.67 1.11.08 1.69 1.14 1.69 1.14.98 1.68 2.57 1.2 3.2.92.1-.71.39-1.2.7-1.48-2.44-.28-5.01-1.22-5.01-5.43 0-1.2.43-2.18 1.13-2.95-.11-.28-.49-1.4.1-2.92 0 0 .93-.3 3.04 1.13a10.6 10.6 0 0 1 2.77-.37c.94 0 1.89.13 2.77.37 2.11-1.43 3.04-1.13 3.04-1.13.6 1.52.22 2.64.11 2.92.71.77 1.13 1.75 1.13 2.95 0 4.22-2.58 5.15-5.03 5.42.4.34.75 1.02.75 2.05 0 1.48-.01 2.67-.01 3.03 0 .29.2.64.76.53A11.03 11.03 0 0 0 23.01 11.51C23.01 5.24 18.27.5 12 .5Z" />
    </svg>
  );
}

export function PlayMarkIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className={cn("h-5 w-5", className)}
    >
      <defs>
        <linearGradient id="vp-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#7c5cff" />
          <stop offset="100%" stopColor="#00d4ff" />
        </linearGradient>
      </defs>
      <path d="M7 4.5 L19.5 12 L7 19.5 Z" fill="url(#vp-mark)" />
    </svg>
  );
}
