import { useEffect } from 'react';

export default function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · AI Data Analyst Agent` : 'AI Data Analyst Agent';
  }, [title]);
}
