import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/hanken-grotesk/wght.css';
import '@fontsource/fragment-mono/latin-400.css';
import { App } from './App';
import './style.css';
import './workbench.css';

createRoot(document.getElementById('app')!).render(<StrictMode><App /></StrictMode>);
