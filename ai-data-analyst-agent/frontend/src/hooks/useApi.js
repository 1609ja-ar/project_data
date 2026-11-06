import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api.js';
import { errorMessage } from '../services/errors.js';

/** GET (or POST, for read-only computed views) a URL and track loading/error/data. Pass null to skip. */
export default function useApi(url, { params, deps = [], method = 'get', body } = {}) {
  const [state, setState] = useState({ data: null, loading: Boolean(url), error: null });
  const seq = useRef(0);
  const key = JSON.stringify([params || {}, method, body || null]);

  const load = useCallback(async () => {
    if (!url) {
      setState({ data: null, loading: false, error: null });
      return null;
    }
    const n = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const { data } = method === 'post' ? await api.post(url, body || {}, { params }) : await api.get(url, { params });
      if (n === seq.current) setState({ data, loading: false, error: null });
      return data;
    } catch (err) {
      if (n === seq.current) setState({ data: null, loading: false, error: errorMessage(err) });
      return null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, key, ...deps]);

  useEffect(() => {
    load();
  }, [load]);

  return { ...state, reload: load, setData: (d) => setState((s) => ({ ...s, data: typeof d === 'function' ? d(s.data) : d })) };
}

export function useDebounced(value, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
