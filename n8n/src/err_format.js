// FORMAT ERROR — turns the Error Trigger payload into one row for Google Sheets.
const e = $input.first().json;
const message = String(e.execution?.error?.message || e.trigger?.error?.message || 'unknown error');
const id = message.match(/NR-\d{8}-[A-Z0-9]{4}/);
return [{
  json: {
    at: new Date().toISOString(),
    workflow: e.workflow?.name || '',
    exec_id: String(e.execution?.id ?? ''),
    video_id: id ? id[0] : '',
    failed_node: e.execution?.lastNodeExecuted || '',
    error: message.slice(0, 1000),
    execution_url: e.execution?.url || '',
  },
}];
