import React from 'react';
import {createRoot} from 'react-dom/client';
import Home from '../app/page';
import '../app/globals.css';
import '../app/live.css';
import '../app/huntx-theme.css';
import '../app/huntx-archive.css';
createRoot(document.getElementById('root')!).render(<React.StrictMode><Home/></React.StrictMode>);
