import test from 'node:test';
import assert from 'node:assert/strict';
import {backendOrigin, publicProductURL, sameSite, verdict, clipSize, captureWarnings, readableText} from './policy.mjs';

test('legacy messages recover accents and apostrophes without altering valid French', () => {
  assert.equal(readableText('ReÃ§u par FaithBook : exÃ©cution #3732'), 'Reçu par FaithBook : exécution #3732');
  assert.equal(readableText('VÃ©rifiez lâ€™appairage ou lâ€™historique.'), 'Vérifiez l’appairage ou l’historique.');
  for (const text of ['Reçu par FaithBook : exécution #3732', 'À vérifier — prêt à l’emploi…', 'Texte déjà correct ✅', 'âge : 42', 'Séquence incomplète Ã']) assert.equal(readableText(text), text);
});
test('repair handles double encoding and mixed valid text', () => {
  assert.equal(readableText('ReÃƒÂ§u : exÃƒÂ©cution'), 'Reçu : exécution');
  assert.equal(readableText('Déjà prêt — exÃ©cution reçue ✅'), 'Déjà prêt — exécution reçue ✅');
});

test('backend HTTPS, sans identifiants ni chemin', () => {
  assert.equal(backendOrigin('https://faithbook.example/'), 'https://faithbook.example');
  for (const value of ['http://example.com', 'https://secret@example.com', 'https://example.com/api', 'https://www.walmart.com/']) assert.throws(() => backendOrigin(value));
});
test('les redirections restent sur la cible autorisée', () => {
  assert(sameSite('https://www.basspro.com/', 'https://www.basspro.com/home'));
  for (const value of ['https://evil.test/', 'https://www.basspro.com.evil.test/', 'http://www.basspro.com/', 'https://user@www.basspro.com/']) assert(!sameSite('https://www.basspro.com/', value));
});
test('un défi tardif et une page erreur ne sont pas des réussites', () => {
  assert.equal(verdict({title:'Walmart', text:'products '.repeat(1000)+'Robot or human?'}), 'challenge');
  assert.equal(verdict({title:'Bass Pro', text:'Something went wrong. '.repeat(10)}), 'capture');
  assert.equal(verdict({title:'Academy', text:'Shop outdoor clothing and shoes. '.repeat(5)}), 'success');
});
test('ne pas tronquer silencieusement une page trop grande', () => {
  assert.deepEqual(clipSize(1440, 2000), {x:0,y:0,width:1440,height:2000,scale:1,truncated:false});
  assert.deepEqual(clipSize(1000, 17000), {x:0,y:0,width:1000,height:16000,scale:1,truncated:true});
  assert.deepEqual(clipSize(2400, 16000), {x:0,y:0,width:2400,height:10000,scale:1,truncated:true});
  assert.equal(clipSize(3000, 2000).width, 2400);
  assert.throws(() => clipSize(1000, 50));
});

test('fiches multi-enseignes publiques et isolement des redirections', () => {
  assert(publicProductURL('https://www.amazon.com/dp/product'));
  assert(publicProductURL('https://www.reconyx.com/product/test?color=1'));
  for (const u of ['http://127.0.0.1/a','https://localhost/a','http://0x7f000001/','https://[::1]/','file:///tmp/x','https://host.internal/a','https://user:pass@public.com/']) assert(!publicProductURL(u),u);
  assert(!sameSite('https://www.reconyx.com/product/a','https://www.amazon.com/'));
});

test('404 et écran Amazon ne sont jamais validés comme une fiche produit', () => {
  for (const text of ["We couldn’t find this page. Try searching or go to the homepage.",
    "SHOOT! THE PAGE YOU WERE LOOKING FOR COULDN'T BE FOUND.", '404: Not found. Contact support for more information.']) {
    assert.equal(verdict({title:'Products', text}), 'navigation');
  }
  assert.equal(verdict({title:'Amazon', text:'Click the button below to continue shopping. Continue shopping.'}), 'challenge');
});

test('les avertissements donnent la hauteur réellement capturée et les ressources manquantes', () => {
  const clipped = clipSize(2400, 16000);
  const reason = captureWarnings(clipped, {pending:2, broken:1, fonts_pending:true});
  assert.match(reason, /10 000|10000/);
  assert.match(reason, /2 image\(s\) encore en chargement/);
  assert.match(reason, /1 image\(s\) indisponible/);
  assert.match(reason, /Polices/);
  assert.equal(captureWarnings(clipSize(1440,2000), {pending:0, broken:0, fonts_pending:false}), '');
});
