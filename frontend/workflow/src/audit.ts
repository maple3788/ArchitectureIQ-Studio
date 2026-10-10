/** Prefer the last transport serialization; logical messages are not a sent-input receipt. */
export function auditRecord(record: any) {
  const request =
    record?.actual_request ?? record?.transport?.request ?? record?.request;
  const payload = request?.payload ?? request?.json ?? request;
  const response =
    record?.raw ??
    record?.raw_response ??
    record?.transport?.response ??
    record?.response;
  return {
    request,
    response,
    messages: payload?.messages,
    questionKey:
      record?.inputs?.question_key ??
      record?.question_key ??
      record?.question_id,
    modelId: record?.inputs?.model_id ?? record?.model_id,
    nodeId: record?.inputs?.node_id ?? record?.node_id ?? record?.role,
    finishReason:
      record?.finish_reason ?? response?.choices?.[0]?.finish_reason,
    usage: record?.usage ?? response?.usage,
  };
}
