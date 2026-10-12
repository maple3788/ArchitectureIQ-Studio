"""Human-only answer commitment and stored result disclosure."""
from fastapi import Body, HTTPException

from architecture_iq.studio.human_practice import PracticeConflict, review_question


def register_human_practice_routes(api, *, catalog, observer):
    @api.post('/api/studio/questions/review')
    def review(body: dict = Body(...)):
        try:
            return review_question(catalog, observer, body)
        except PracticeConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, '题目或已保存的结果不可用') from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, '请先选择这道题的一个有效选项再提交') from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(503, '已保存的题目结果暂时无法读取，请稍后重试') from exc
