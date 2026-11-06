import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { CornerDownLeft, MessageSquare } from 'lucide-react';

/** Topbar question box. Ctrl/Cmd+K focuses it from anywhere; Enter answers on the Ask page
 *  for the dataset that is open (if the current page has one). */
export default function AskBar() {
  const navigate = useNavigate();
  const location = useLocation();
  const [q, setQ] = useState('');
  const ref = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const submit = (e) => {
    e.preventDefault();
    const question = q.trim();
    if (question.length < 3) return;
    const p = new URLSearchParams({ q: question });
    const current = new URLSearchParams(location.search).get('dataset') || location.pathname.match(/\/datasets\/(\w+)/)?.[1];
    if (current) p.set('dataset', current);
    navigate(`/app/ask?${p}`);
    setQ('');
    ref.current?.blur();
  };

  return (
    <form className="askbar" onSubmit={submit} role="search">
      <MessageSquare size={15} className="askbar-icon" aria-hidden="true" />
      <input ref={ref} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about your data, e.g. top 5 products by revenue"
        aria-label="Ask a question about your data" maxLength={300} />
      {q ? <CornerDownLeft size={14} className="askbar-kbd" aria-hidden="true" /> : <kbd className="askbar-kbd">Ctrl K</kbd>}
    </form>
  );
}
