import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/postcss';
import {fileURLToPath} from 'node:url';
export default defineConfig({
 root:fileURLToPath(new URL('.',import.meta.url)),
 base:'/nouvelle-interface/',
 publicDir:fileURLToPath(new URL('../public',import.meta.url)),
 resolve:{alias:{'@':fileURLToPath(new URL('..',import.meta.url))}},
 plugins:[react()],
 css:{postcss:{plugins:[tailwindcss()]}},
 build:{outDir:fileURLToPath(new URL('../dist-hetzner',import.meta.url)),emptyOutDir:true}
});
