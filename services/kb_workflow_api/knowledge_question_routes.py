"""Local, read-only per-knowledge question applicability."""
from fastapi import HTTPException, Query

from architecture_iq.studio.knowledge_questions import KnowledgeReferenceConflict, knowledge_questions


def register_knowledge_question_routes(api, *, catalog, inventory_provider):
    @api.get('/api/studio/kb/questions')
    def questions(kb_id: str = Query(..., min_length=1, max_length=512),
                  kb_version: str = Query(..., min_length=1, max_length=128),
                  claim_id: str = Query(..., min_length=1, max_length=1000),
                  relation: str = Query('all', pattern='^(all|applicable|inapplicable|unknown)$'),
                  search: str = Query('', max_length=200), offset: int = Query(0, ge=0),
                  limit: int = Query(25, ge=1, le=100)):
        try:
            return knowledge_questions(catalog, inventory_provider(),
                reference={'id': kb_id, 'version': kb_version}, claim_id=claim_id,
                relation=relation, search=search, offset=offset, limit=limit)
        except KnowledgeReferenceConflict as exc:
            raise HTTPException(409, 'KB 的固定版本或规则校验失败，请重新选择知识条目') from exc
        except KeyError as exc:
            raise HTTPException(404, '所选知识条目或固定 KB 版本不存在') from exc
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(422, '知识条目或题目筛选条件不可用') from exc
