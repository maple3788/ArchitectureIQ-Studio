"""Before-answer knowledge reading; no answer commitment or result access."""
from fastapi import Body, HTTPException

from architecture_iq.studio.human_practice import PracticeConflict
from architecture_iq.studio.question_applicability import applicable_knowledge


def register_question_applicability_routes(api, *, catalog, observer, evolution, inventory_provider):
    @api.post('/api/studio/questions/applicable-knowledge')
    def applicable(body: dict = Body(...)):
        try:
            return applicable_knowledge(catalog, observer, evolution, inventory_provider(), body)
        except PracticeConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, '题目或指定的知识版本不可用') from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, '公开题目或知识引用无效，请重新打开后重试') from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(503, '公开资料暂时无法读取，请稍后重试') from exc
