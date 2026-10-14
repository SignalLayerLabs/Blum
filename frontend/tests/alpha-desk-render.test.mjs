import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as view from '../lib/alphaDeskView.mjs';

// Exercise the shipped component; stub only terminal layout and badge wrappers.
test('an excluded malformed provider cannot crash the actual Alpha Desk journal',()=>{
  const source=fs.readFileSync(new URL('../components/AlphaDesk.tsx',import.meta.url),'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={};
  const require=createRequire(import.meta.url);
  vm.runInNewContext(code,{exports,require:(name)=>{
    if(name==='@/lib/alphaDeskView.mjs') return view;
    if(name==='@/components/FinancialTerminal') return {BloombergPanel:({children})=>React.createElement('div',{},children)};
    if(name==='@/components/StatusBadge') return {StatusBadge:({label})=>React.createElement('span',{},label)};
    return require(name);
  }});
  const data={registered_count:1,markets:{},journal:[{source_uid:'bad',asset:'SPY',market:'equity',provider:{not:'a name'},blockers:['MISSING_PROVENANCE']}]};
  const html=renderToStaticMarkup(React.createElement(exports.AlphaDesk,{data}));
  assert.match(html,/unattributed/);
  assert.match(html,/MISSING_PROVENANCE/);
});
