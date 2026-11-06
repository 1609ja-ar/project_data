import { forwardRef, useImperativeHandle, useMemo, useRef } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { keymap } from '@codemirror/view';
import { Prec } from '@codemirror/state';
import { sql, PostgreSQL } from '@codemirror/lang-sql';

/** CodeMirror SQL editor: highlighting, schema autocomplete, theme follows the app, Ctrl/Cmd+Enter runs. */
const SqlEditor = forwardRef(function SqlEditor({ value, onChange, onRun, schema, dark }, ref) {
  const viewRef = useRef(null);
  const runRef = useRef(onRun);
  runRef.current = onRun;

  useImperativeHandle(ref, () => ({
    insert(text) {
      const view = viewRef.current;
      if (!view) return false;
      const { from, to } = view.state.selection.main;
      view.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length } });
      view.focus();
      return true;
    },
  }));

  const extensions = useMemo(
    () => [
      sql({ schema, dialect: PostgreSQL, upperCaseKeywords: true, defaultTable: 'data' }),
      Prec.highest(keymap.of([{ key: 'Mod-Enter', run: () => { runRef.current?.(); return true; } }])),
    ],
    [schema],
  );

  return (
    <div className="sql-editor" aria-label="SQL editor">
      <CodeMirror
        value={value}
        height="240px"
        theme={dark ? 'dark' : 'light'}
        extensions={extensions}
        onChange={onChange}
        onCreateEditor={(view) => { viewRef.current = view; }}
        basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: true, autocompletion: true }}
      />
    </div>
  );
});

export default SqlEditor;
