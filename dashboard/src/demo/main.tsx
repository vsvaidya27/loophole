import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/hanken-grotesk/wght.css';
import '@fontsource/fragment-mono/latin-400.css';
import { loadDemo, type DemoData } from './data';
import { LoopDemo } from './LoopDemo';
import './demo.css';

function Page() {
  const [data, setData] = useState<DemoData>();
  const [error, setError] = useState<string>();
  useEffect(() => { loadDemo().then(setData, (e: Error) => setError(e.message)); }, []);
  if (error) return <p className="demo-message">{error}</p>;
  if (!data) return <p className="demo-message">Loading the recorded run…</p>;
  return <LoopDemo embedded={new URLSearchParams(window.location.search).has('embedded')} data={data} autoplay={new URLSearchParams(window.location.search).has('autoplay')} />;
}

createRoot(document.getElementById('demo')!).render(<StrictMode><Page /></StrictMode>);
