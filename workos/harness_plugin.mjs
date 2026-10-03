/** Trusted selected-evidence capabilities; model arguments never become paths or commands. */
import fs from 'node:fs';

export const name = 'workos-evidence-harness';
export const inject = ['tools'];
export const TOOL_NAMES = Object.freeze(['workos_sources','workos_read_source','workos_find_evidence','workos_check_draft']);

export function createEvidenceRuntime(packet, publish = () => {}) {
  if (!packet || !Array.isArray(packet.sources) || packet.sources.length > 80) throw new Error('Invalid selected evidence packet');
  const sources = new Map(packet.sources.map(source => [source.source_id,{...source,chars:Array.from(source.text)}]));
  if (sources.size !== packet.sources.length) throw new Error('Duplicate source ids');
  const trace = {tool_counts:{},read_ranges:[],blocked_tools:[],qa:{}};
  let delivered = 0, calls = 0;
  const save = () => publish(JSON.parse(JSON.stringify(trace)));
  const selected = id => { if (!sources.has(id)) throw new Error('Only explicitly selected source ids are allowed'); return sources.get(id); };
  const admit = name => {
    if (calls >= packet.tool_budget) throw new Error('WorkOS tool-call budget exhausted');
    // Reserve final checks even when evidence calls consume their allowance.
    if (name !== 'workos_check_draft' && calls >= packet.tool_budget-4) throw new Error('WorkOS evidence-call budget exhausted; check the draft now');
    calls++;
    trace.tool_counts[name] = (trace.tool_counts[name] || 0)+1;
  };
  const read = (source,start,length) => {
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(length) || start < 0 || start >= source.chars.length || length < 1 || length > 12000) throw new Error('Invalid source range; length must be 1–12000 characters');
    const end = Math.min(source.chars.length,start+length);
    if (delivered+end-start > packet.read_budget) throw new Error('WorkOS evidence budget exhausted; remaining materials are unreviewed');
    delivered += end-start;
    trace.read_ranges.push({source_id:source.source_id,start,end});
    return {source_id:source.source_id,start,end,text:source.chars.slice(start,end).join(''),total_chars:source.chars.length,more:end < source.chars.length};
  };
  const check = draft => {
    if (typeof draft !== 'string' || !draft.trim() || Array.from(draft).length > 1000000) throw new Error('Invalid draft text');
    const tags = [...draft.matchAll(/\[S(\d+)\]/g)].map(match=>'S'+match[1]);
    const errors = [];
    for (const tag of new Set(tags)) if (!sources.has(tag)) errors.push('Unknown citation '+tag);
    if (sources.size && !tags.length) errors.push('Selected evidence requires citations');
    if (/<\s*(script|iframe|object|embed)\b/i.test(draft)) errors.push('Executable markup is not allowed');
    for (const tag of new Set(tags)) if (sources.has(tag) && !trace.read_ranges.some(row=>row.source_id===tag)) errors.push('Citation source has not been read through the evidence tool: '+tag);
    const result = {valid:!errors.length,errors,citation_ids:[...new Set(tags)],
      limitations:['Deterministic scope and citation checks do not prove semantic factual correctness.']};
    trace.qa = {...result,draft};
    return result;
  };
  return {
    trace,
    deny(tool) {
      trace.blocked_tools.push(String(tool).slice(0,100));
      if (trace.blocked_tools.length > 128) trace.blocked_tools.shift();
      save();
      return 'WorkOS denies tools outside selected evidence; no filesystem, shell, network or subagents';
    },
    execute(tool,args = {}) {
      if (!TOOL_NAMES.includes(tool)) throw new Error(this.deny(tool));
      admit(tool);
      let result;
      try {
        if (tool === 'workos_sources') result = {sources:[...sources.values()].map(({source_id,document_id,title,version,chars})=>({source_id,document_id,title,version,total_chars:chars.length})),read_budget_remaining:packet.read_budget-delivered,tool_calls_remaining:packet.tool_budget-calls};
        if (tool === 'workos_read_source') result = read(selected(args.source_id),args.start,args.length);
        if (tool === 'workos_find_evidence') {
          if (typeof args.query !== 'string' || Array.from(args.query).length < 2 || args.query.length > 200) throw new Error('Query must contain 2–200 characters');
          const targets = args.source_id ? [selected(args.source_id)] : [...sources.values()];
          const matches = [];
          for (const source of targets) {
            const lower = source.chars.map(char=>char.toLowerCase());
            const needle = Array.from(args.query).map(char=>char.toLowerCase());
            for (let position=0;position <= lower.length-needle.length && matches.length < 5;position++) {
              if (needle.every((char,index)=>char===lower[position+index])) {
                const start = Math.max(0,position-200);
                matches.push(read(source,start,Math.min(500,source.chars.length-start)));
                position += needle.length-1;
              }
            }
            if (matches.length >= 5) break;
          }
          result = {matches,remaining_chars:packet.read_budget-delivered};
        }
        if (tool === 'workos_check_draft') result = check(args.draft);
        return result;
      } finally { save(); }
    }
  };
}

export async function apply(ctx, config) {
  // This module needs only the injected registry API, not globally installed npm resolution.
  const packet = JSON.parse(fs.readFileSync(config.packetPath,'utf8'));
  const runtime = createEvidenceRuntime(packet,trace=>fs.writeFileSync(config.tracePath,JSON.stringify(trace),'utf8'));
  const allowed = new Set(config.native ? TOOL_NAMES : []);
  ctx.tools.guard(exec=>allowed.has(exec.name) ? undefined : runtime.deny(exec.name));
  if (config.native) {
    const schemas = {
      workos_sources:{description:'List the exact user-selected evidence manifest, versions and read budget.',properties:{}},
      workos_read_source:{description:'Read a selected source by Unicode-character range; read consecutive ranges to cover its full text. Never accept paths.',properties:{source_id:{type:'string'},start:{type:'integer'},length:{type:'integer'}},required:['source_id','start','length']},
      workos_find_evidence:{description:'Find exact words only inside selected sources. Returned matches count toward the explicit read budget, not full coverage.',properties:{query:{type:'string'},source_id:{type:'string'}},required:['query']},
      workos_check_draft:{description:'Check the exact proposed final Markdown for selected-source citation validity and scope. After a successful check, final text must match this draft exactly.',properties:{draft:{type:'string'}},required:['draft']}
    };
    for (const tool of TOOL_NAMES) {
      const schema = schemas[tool];
      ctx.tools.register({name:tool,description:schema.description,
        parameters:{type:'object',properties:schema.properties,required:schema.required || [],additionalProperties:false},
        output:{schema:{type:'object',additionalProperties:true},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},
        execute:async args=>runtime.execute(tool,args),isConcurrencySafe:()=>false});
    }
  }
  // Creation hooks finish before the first request; guard remains authoritative for scoped registrations.
  ctx.on('agent/created',({agent})=> {
    agent.ctx.tools.presentAs('native');
    if (allowed.size) agent.ctx.tools.restrict({allow:[...allowed]});
    else {
      const names = ctx.tools.schemas().map(schema=>schema.name);
      if (names.length) agent.ctx.tools.restrict({deny:names});
    }
  });
}
