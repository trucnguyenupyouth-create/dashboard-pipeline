import json
import logging
from django.db.models import Sum, Q
from ..models import VisionGradingResult, VisionGradingStep, ExamAnalyticsCache, Submission, Exam, Question, SubmissionReport
from google import genai
from google.genai import types as genai_types
import google.generativeai as legacy_genai
from .analytics_prompt import ANALYTICS_SYSTEM_PROMPT, get_analytics_system_prompt
from .curriculum_context import get_curriculum_constants_for_grade
from .supabase_cache import get_cached_analytics, upsert_cached_analytics

logger = logging.getLogger(__name__)

class ExamAnalyticsService:
    def __init__(self, model_name="gemini-3-flash-preview", api_key=None):
        self.model_name = model_name
        self.api_key = api_key

    def compute_analytics(self, exam_id: int, force_refresh=False) -> dict:
        """
        Main entry point. Computes Phase 1 (deterministic) and Phase 2 (AI-powered) analytics.
        Returns the combined JSON payload matching the dashboard's data contract.
        """
        # Check cache unless forcing refresh
        if not force_refresh:
            try:
                cache = ExamAnalyticsCache.objects.get(exam_id=exam_id)
                return cache.analytics_json
            except ExamAnalyticsCache.DoesNotExist:
                # Fallback: Try reading from Supabase cache
                supabase_data = get_cached_analytics(exam_id)
                if supabase_data and "analytics_json" in supabase_data:
                    logger.info(f"Cache miss on local DB for exam {exam_id}, but found in Supabase. Back-filling local cache.")
                    try:
                        ExamAnalyticsCache.objects.update_or_create(
                            exam_id=exam_id,
                            defaults={
                                'analytics_json': supabase_data['analytics_json'],
                                'model_name': supabase_data.get('model_name', self.model_name),
                                'version': supabase_data.get('version', 1)
                            }
                        )
                    except Exception as local_err:
                        logger.error(f"Failed to back-fill local cache for exam {exam_id}: {local_err}")
                    return supabase_data['analytics_json']
            except Exception as e:
                logger.error(f"Local cache read failed: {e}")
                # Fallback: Try reading from Supabase cache
                supabase_data = get_cached_analytics(exam_id)
                if supabase_data and "analytics_json" in supabase_data:
                    return supabase_data['analytics_json']

        logger.info(f"Computing analytics for exam {exam_id}")
        
        # --- Phase 1: Deterministic Data ---
        exam, questions, submissions, results, steps, reports = self._load_data(exam_id)
        
        if not submissions:
            return {"error": "No submissions found for this exam"}

        score_matrix = self._build_score_matrix(submissions, results, questions, reports)
        students_with_groups = self._assign_groups(score_matrix)
        class_metrics = self._compute_class_metrics(students_with_groups)
        students_with_risk = self._compute_risk_scores(students_with_groups, steps)
        student_groups = self._build_student_groups(students_with_risk)
        group_weaknesses = self._compute_group_weaknesses(student_groups, score_matrix)

        # --- Phase 2: AI-Powered Analysis ---
        ai_response = self._run_ai_analysis(exam, questions, steps, student_groups, score_matrix, group_weaknesses)

        # --- Assembly: Merge Deterministic + AI Data ---
        final_payload = self._assemble_final_output(
            class_metrics, 
            students_with_risk, 
            student_groups, 
            group_weaknesses, 
            ai_response,
            score_matrix,
            questions,
            steps
        )

        # Cache result - local Django DB
        try:
            ExamAnalyticsCache.objects.update_or_create(
                exam_id=exam_id,
                defaults={
                    'analytics_json': final_payload,
                    'model_name': self.model_name,
                    'version': 1
                }
            )
        except Exception as e:
            logger.error(f"Failed to save cache to local Django DB: {e}")

        # Cache result - Supabase (parallel write)
        upsert_cached_analytics(exam_id, final_payload, self.model_name)

        return final_payload

    def _load_data(self, exam_id: int):
        exam = Exam.objects.get(id=exam_id)
        questions = list(Question.objects.filter(exam_id=exam_id))
        submissions = list(Submission.objects.filter(exam_id=exam_id))
        sub_ids = [s.id for s in submissions]
        
        # Only use latest results
        results = list(VisionGradingResult.objects.filter(
            submission_id__in=sub_ids, 
            is_latest=True
        ))
        
        res_ids = [r.id for r in results]
        steps = list(VisionGradingStep.objects.filter(grading_result_id__in=res_ids))

        # Load AI report markdown per submission (contains authoritative score like '5.25/10')
        reports = {r.submission_id: r for r in SubmissionReport.objects.filter(submission_id__in=sub_ids)}
        
        return exam, questions, submissions, results, steps, reports

    def _build_score_matrix(self, submissions, results, questions, reports=None):
        """Builds deduplicated score matrix mapping (sub_id, q_id) to score and status.
        
        Score priority (same as CSV/Excel export):
        1. Submission.override_total_score  — teacher manual override
        2. SubmissionReport.report_markdown  — regex-extracted score (e.g. '5.25/10') — authoritative
        3. raw_sum of VisionGradingResult.score — fallback if no report exists
        """
        import re
        REPORT_SCORE_RE = re.compile(
            r'\u0110i\u1ec3m(?:\s+s\u1ed1)?\s*[:]\s*(?:\*\*|)\s*([\d\.]+(?:/\d+)?)',
            re.IGNORECASE
        )
        reports = reports or {}

        # Fix is_latest duplication by taking the most recently updated result per (submission, question)
        results.sort(key=lambda x: x.updated_at, reverse=True)
        dedup_results = {}
        for r in results:
            key = (r.submission_id, r.question_id)
            if key not in dedup_results:
                dedup_results[key] = r

        # Infer max scores if needed
        q_max_scores = {}
        for q in questions:
            if q.max_score and q.max_score > 0:
                q_max_scores[q.id] = q.max_score
            else:
                # Infer max score from observed scores
                q_results = [r for r in dedup_results.values() if r.question_id == q.id and r.score is not None]
                if q_results:
                    q_max_scores[q.id] = max((r.score for r in q_results))
                else:
                    q_max_scores[q.id] = 1.0 # Ultimate fallback

        # Total score priority:
        # 1. override_total_score — teacher manual override
        # 2. raw_sum — sum of VisionGradingResult.score (already 0.25-rounded per question by AI)
        # NOTE: Do NOT normalize to 10. Matrix-mode exams have scores like 12.25 which IS correct.
        exam_max_total = sum(q_max_scores.values()) if q_max_scores else 10.0

        matrix = {}
        for s in submissions:
            matrix[s.id] = {
                'submission': s,
                'total_score': 0.0,
                'results': {}
            }
            raw_sum = 0.0
            for q in questions:
                r = dedup_results.get((s.id, q.id))
                score = r.score if r and r.score is not None else 0.0
                max_s = q_max_scores[q.id]
                status = "unattempted"
                if r:
                    if r.is_correct:
                        status = "correct"
                    elif r.is_unattempted:
                        status = "unattempted"
                    elif score > 0:
                        status = "partial"
                    else:
                        status = "incorrect"
                        
                matrix[s.id]['results'][q.id] = {
                    'score': score,
                    'maxScore': max_s,
                    'status': status,
                    'label': q.label
                }
                raw_sum += score
            
            # Score priority chain (matches CSV/Excel export logic):
            # 1. override_total_score — teacher manual override (highest priority)
            # 2. report_markdown regex — AI report's stated score like "5.25/10" (authoritative)
            # 3. raw_sum of VisionGradingResult.score — fallback
            if getattr(s, 'override_total_score', None) is not None:
                matrix[s.id]['total_score'] = float(s.override_total_score)
            else:
                report = reports.get(s.id)
                report_score = None
                if report and report.report_markdown:
                    match = REPORT_SCORE_RE.search(report.report_markdown)
                    if match:
                        try:
                            report_score = float(match.group(1).split('/')[0])
                        except (ValueError, IndexError):
                            pass
                matrix[s.id]['total_score'] = report_score if report_score is not None else round(raw_sum, 2)

        return matrix

    def _assign_groups(self, score_matrix):
        """Assign groups based on total score."""
        for s_id, data in score_matrix.items():
            score = data['total_score']
            if score >= 8.0:
                data['group'] = 'Giỏi'
            elif score >= 6.5:
                data['group'] = 'Khá'
            elif score >= 5.0:
                data['group'] = 'TB'
            else:
                data['group'] = 'Yếu'
        return score_matrix

    def _compute_class_metrics(self, students_with_groups):
        scores = [d['total_score'] for d in students_with_groups.values()]
        total = len(scores)
        if total == 0:
            return {"totalStudents": 0, "averageScore": 0, "highestScore": 0, "lowestScore": 0, "attendanceRate": 0}
            
        return {
            "totalStudents": total,
            "averageScore": round(sum(scores) / total, 2),
            "highestScore": max(scores),
            "lowestScore": min(scores),
            "attendanceRate": 100 # Default for now
        }

    def _compute_risk_scores(self, students_with_groups, steps):
        """Calculate deterministic risk score."""
        # Count critical original errors per student
        student_error_counts = {}
        for step in steps:
            if step.is_correct == False and step.error_classification == 'original':
                res = step.grading_result
                student_error_counts[res.submission_id] = student_error_counts.get(res.submission_id, 0) + 1

        for s_id, data in students_with_groups.items():
            score = data['total_score']
            max_possible = 10.0
            
            score_comp = max(0, (1 - score / max_possible)) * 60
            err_count = student_error_counts.get(s_id, 0)
            severity_comp = min(err_count * 4, 40)
            
            risk = min(100, round(score_comp + severity_comp))
            data['riskScore'] = risk
            data['riskBreakdown'] = {
                'averageScore': round(score_comp, 1),
                'severity': round(severity_comp, 1),
                'trend': 0,
                'total': risk
            }
            data['original_error_count'] = err_count
            
        return students_with_groups

    def _build_student_groups(self, students_with_risk):
        groups = {
            "Giỏi": {"id": "1", "name": "Nhóm Giỏi", "level": "Giỏi", "count": 0, "total_score": 0, "students": [], "riskLevel": "Thấp"},
            "Khá": {"id": "2", "name": "Nhóm Khá", "level": "Khá", "count": 0, "total_score": 0, "students": [], "riskLevel": "Thấp"},
            "TB": {"id": "3", "name": "Nhóm TB", "level": "TB", "count": 0, "total_score": 0, "students": [], "riskLevel": "Trung bình"},
            "Yếu": {"id": "4", "name": "Nhóm Yếu", "level": "Yếu", "count": 0, "total_score": 0, "students": [], "riskLevel": "Cao"},
        }
        
        total_students = len(students_with_risk)
        
        for s_id, data in students_with_risk.items():
            g = data['group']
            groups[g]['count'] += 1
            groups[g]['total_score'] += data['total_score']
            groups[g]['students'].append({
                "id": str(s_id),
                "name": data['submission'].student_name or f"Student {s_id}",
                "score": data['total_score'],
                "riskScore": data['riskScore'],
                "group": g
            })
            
        for g_name, g_data in groups.items():
            g_data['percentage'] = round((g_data['count'] / total_students) * 100, 1) if total_students > 0 else 0
            g_data['averageScore'] = round(g_data['total_score'] / g_data['count'], 2) if g_data['count'] > 0 else 0
            
        return groups

    def _compute_group_weaknesses(self, student_groups, score_matrix):
        group_weaknesses = {"Giỏi": [], "Khá": [], "TB": [], "Yếu": []}
        
        # For each group, find questions where >50% scored 0 or <= half max
        for group_name, group_data in student_groups.items():
            group_student_ids = [int(s['id']) for s in group_data['students']]
            if not group_student_ids:
                continue
                
            q_stats = {}
            for s_id in group_student_ids:
                for q_id, q_data in score_matrix[s_id]['results'].items():
                    if q_id not in q_stats:
                        q_stats[q_id] = {'label': q_data['label'], 'fail_count': 0, 'total': 0}
                    q_stats[q_id]['total'] += 1
                    if q_data['score'] <= (q_data['maxScore'] / 2):
                        q_stats[q_id]['fail_count'] += 1
                        
            for q_id, stats in q_stats.items():
                if stats['total'] > 0 and (stats['fail_count'] / stats['total']) > 0.5:
                    perc = round((stats['fail_count'] / stats['total']) * 100)
                    group_weaknesses[group_name].append({
                        "question_label": stats['label'],
                        "percentage": perc,
                        "description": f"{stats['fail_count']}/{stats['total']} học sinh {group_name} không làm được hoặc bị điểm kém {stats['label']}"
                    })
                    
        return group_weaknesses

    def _run_ai_analysis(self, exam, questions, steps, student_groups, score_matrix, group_weaknesses):
        """Phase 2: Single structured LLM call to get topics, error taxonomy, and interventions."""
        # 1. Format Questions
        q_text_lines = []
        q_map = {}
        for q in questions:
            q_map[q.id] = q.label
            q_text_lines.append(f"### {q.label}")
            q_text_lines.append(f"Nội dung: {getattr(q, 'content_summary', '') or ''}")
            q_text_lines.append("---")
        q_text = "\n".join(q_text_lines)

        # 2. Errors grouped by question
        bad_steps = [s for s in steps if not s.is_correct and s.error_classification in ('original', 'critical', 'none')]
        errors_by_q = {}
        for s in bad_steps:
            q_label = q_map.get(s.grading_result.question_id, "?")
            errors_by_q.setdefault(q_label, []).append(s)
            
        error_text_lines = []
        for q_label, s_list in errors_by_q.items():
            unique_students = len(set(s.grading_result.submission_id for s in s_list))
            error_text_lines.append(f"### Câu {q_label} — {len(s_list)} lỗi từ {unique_students} học sinh")
            error_text_lines.append("| Student ID | Bước sai | Feedback chấm |")
            error_text_lines.append("|------------|----------|---------------|")
            for s in s_list[:30]: # limit to avoid blown budget
                feedback_clean = s.feedback.replace('\n', ' ') if s.feedback else ''
                step_clean = s.description.replace('\n', ' ') if s.description else ''
                error_text_lines.append(f"| {s.grading_result.submission_id} | {step_clean} | {feedback_clean} |")
            error_text_lines.append("---\n")
        error_text = "\n".join(error_text_lines)

        # 3. Student Score Matrix
        score_text_lines = []
        sorted_qs = sorted(questions, key=lambda x: x.label)
        q_headers = " | ".join(q.label for q in sorted_qs)
        score_text_lines.append(f"| Student ID | Tên | Tổng | {q_headers} |")
        header_sep = "|------------|-----|------|" + "|".join("---" for _ in sorted_qs) + "|"
        score_text_lines.append(header_sep)
        
        for g_name, g_data in student_groups.items():
            for s in g_data['students']:
                s_id = int(s['id'])
                s_name = s['name']
                total = s['score']
                row_scores = []
                for q in sorted_qs:
                    res = score_matrix[s_id]['results'].get(q.id, {})
                    score = res.get('score', 0)
                    max_s = res.get('maxScore', 1)
                    row_scores.append(f"{score}/{max_s}")
                score_text_lines.append(f"| {s_id} | {s_name} | {total} | {' | '.join(row_scores)} |")
        score_text = "\n".join(score_text_lines)

        # 4. Group Performance (from group_weaknesses)
        perf_text_lines = []
        for g_name, weaknesses in group_weaknesses.items():
            count = student_groups[g_name]['count']
            avg = student_groups[g_name]['averageScore']
            perf_text_lines.append(f"Nhóm {g_name} ({count} học sinh, trung bình {avg}/10):")
            if weaknesses:
                perf_text_lines.append("| Câu | Tỉ lệ sai |")
                perf_text_lines.append("|-----|-----------|")
                for w in weaknesses:
                    perf_text_lines.append(f"| {w['question_label']} | {w['percentage']}% |")
            else:
                perf_text_lines.append("Không có điểm yếu nổi bật.")
            perf_text_lines.append("")
        perf_text = "\n".join(perf_text_lines)

        # 5. Group Summary
        group_text_lines = []
        for g_name, g_data in student_groups.items():
            count = g_data['count']
            avg = g_data['averageScore']
            group_text_lines.append(f"Nhóm {g_name} ({count} HS, TB: {avg}):")
            for s in g_data['students']:
                group_text_lines.append(f"  - {s['name']}: {s['score']} điểm")
            group_text_lines.append("")
        group_text = "\n".join(group_text_lines)

        # --- Build lowest-scoring student context for ai_insights ---
        all_students_scores = [
            (s_data['submission'].student_name or f"HS{s_id}", s_data['total_score'], int(s_id))
            for s_id, s_data in score_matrix.items()
        ]
        all_students_scores.sort(key=lambda x: x[1])
        lowest_name, lowest_score, lowest_id = all_students_scores[0] if all_students_scores else ("Chưa xác định", 0, 0)
        total_students = len(all_students_scores)
        class_avg = sum(s[1] for s in all_students_scores) / total_students if total_students else 0

        # Build student name lookup for unattempted table
        student_id_to_name = {}
        for g_name, g_data in student_groups.items():
            for s in g_data['students']:
                student_id_to_name[int(s['id'])] = s['name']

        # Build unattempted table: students who skipped each question entirely
        unattempted_lines = ["| Student ID | Tên | Câu bỏ |"]
        unattempted_lines.append("|------------|-----|--------|")
        has_unattempted = False
        for s_id, s_data in score_matrix.items():
            skipped = [q_data['label'] for q_data in s_data['results'].values()
                       if q_data.get('status') == 'unattempted']
            if skipped:
                has_unattempted = True
                name = student_id_to_name.get(int(s_id), f"HS{s_id}")
                unattempted_lines.append(f"| {s_id} | {name} | {', '.join(skipped)} |")
        unattempted_text = "\n".join(unattempted_lines) if has_unattempted else "(Không có học sinh nào bỏ câu)"

        prompt = f'''Đề thi: {exam.name} (Lớp {exam.grade_level})

═══════════════════════════════════════════
DANH SÁCH CÂU HỎI
═══════════════════════════════════════════
{q_text}

═══════════════════════════════════════════
CÁC LỖI SAI — NHÓM THEO CÂU HỎI
═══════════════════════════════════════════
{error_text}

═══════════════════════════════════════════
ĐIỂM SỐ TỪNG HỌC SINH THEO TỪNG CÂU
═══════════════════════════════════════════
{score_text}

═══════════════════════════════════════════
HIỆU SUẤT TỪNG NHÓM THEO CÂU
═══════════════════════════════════════════
{perf_text}

═══════════════════════════════════════════
PHÂN NHÓM HỌC SINH
═══════════════════════════════════════════
{group_text}
═══════════════════════════════════════════
THÔNG TIN BỔ SUNG — DÙNG CHO ai_insights
═══════════════════════════════════════════
═══════════════════════════════════════════
DANH SÁCH HỌC SINH BỎ CÂU (KHÔNG LÀM)
═══════════════════════════════════════════
⚠️ Những học sinh trong bảng này KHÔNG được gán vào affectedStudentIds của bất kỳ error entry nào liên quan đến câu họ bỏ — kể cả khi điểm = 0.
{unattempted_text}

LOWEST_SCORING_STUDENT:
  Tên: {lowest_name}
  Điểm: {lowest_score}/10
  Submission ID: {lowest_id}

DIỂM TRUNG BÌNH LẬP: {class_avg:.2f}/10
TỔNG SỐ HỌC SINH: {total_students}
'''
        try:
            # Configure API key — prefer explicitly passed key, then fall back to settings
            from django.conf import settings as dj_settings
            api_key = self.api_key or getattr(dj_settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise ValueError("No Gemini API key configured")

            client = genai.Client(api_key=api_key)
            
            # Configure Thinking Config conditionally
            config_kwargs = {
                "system_instruction": get_analytics_system_prompt(getattr(exam, 'grade_level', None)),
                "response_mime_type": "application/json",
            }
            if "flash" in self.model_name.lower() or "thinking" in self.model_name.lower():
                config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=16000
                )
                
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(**config_kwargs)
            )
            
            # Extract JSON from parts (bypassing thoughts)
            response_text = ""
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if not getattr(part, "thought", False):
                        response_text += part.text or ""
                        
            raw = response_text.strip()
            # Strip markdown code fences if model adds them
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return json.loads(raw)
        except Exception as e:
            logger.error(f"AI Analysis failed: {e}", exc_info=True)
            return {
                "question_topics": {},
                "error_taxonomy": [],
                "group_interventions": {},
                "ai_insights": {
                    "overviewInsight": "",
                    "urgentAction": {"title": "", "description": ""},
                    "suggestedActions": [{"subject": "", "content": ""}, {"subject": "", "content": ""}]
                }
            }

    def _assemble_final_output(self, class_metrics, students_with_risk, student_groups, group_weaknesses, ai_response, score_matrix, questions, steps):
        """Merge deterministic data with AI response into the final payload."""
        topics_ai = ai_response.get("question_topics", {})
        errors_ai = ai_response.get("error_taxonomy", [])
        interventions_ai = ai_response.get("group_interventions", {})

        # Pre-compute mapping of student_id -> student_name
        student_id_to_name = {}
        for s_id, s_data in students_with_risk.items():
            student_id_to_name[int(s_id)] = s_data['submission'].student_name or f"HS{s_id}"

        # Pre-compute: which students had incorrect results per question label
        # q_label -> set of student names who scored <= 50% on that question
        label_to_struggling_students = {}
        for s_id, s_data in students_with_risk.items():
            s_name = student_id_to_name[int(s_id)]
            for q_id, q_data in s_data['results'].items():
                label = q_data['label']
                if q_data['score'] <= (q_data['maxScore'] / 2.0):
                    label_to_struggling_students.setdefault(label, set()).add(s_name)

        # Build attempted_set: (student_id_int, question_label) pairs where student actually attempted
        attempted_set = set()
        name_to_id = {}  # reverse of student_id_to_name
        for s_id, s_data in students_with_risk.items():
            s_int = int(s_id)
            s_name = student_id_to_name.get(s_int, '')
            if s_name:
                name_to_id[s_name] = s_int
            for q_id, q_data in s_data['results'].items():
                if q_data.get('status') != 'unattempted':
                    attempted_set.add((s_int, q_data['label']))

        # For each AI error, resolve affected students
        for err in errors_ai:
            affected_names = set()
            error_q_labels = set(err.get('affected_questions', []) or err.get('questionIds', []))

            # 1. Primary: Use explicit student IDs from the AI
            #    Filter out students who did not attempt any of the error's questions
            student_ids = err.get('affectedStudentIds', [])
            if student_ids:
                for s_id in student_ids:
                    try:
                        s_int = int(s_id)
                        s_name = student_id_to_name.get(s_int)
                        if not s_name:
                            continue
                        # Only include if student actually attempted at least one error question
                        if error_q_labels and not any((s_int, lbl) in attempted_set for lbl in error_q_labels):
                            continue  # Student skipped all related questions — exclude
                        affected_names.add(s_name)
                    except (ValueError, TypeError):
                        continue

            # 2. Fallback: score-based assignment — only include students who attempted the question
            if not affected_names:
                for label in error_q_labels:
                    for s_name in label_to_struggling_students.get(label, set()):
                        s_int = name_to_id.get(s_name)
                        if s_int and (s_int, label) in attempted_set:
                            affected_names.add(s_name)

            err['_resolved_affected_students'] = list(affected_names)

        # 1. Build Students List
        students_list = []
        for s_id, data in students_with_risk.items():
            q_results = []
            for q_id, q_data in data['results'].items():
                q_results.append({
                    "question": q_data['label'],
                    "score": q_data['score'],
                    "maxScore": q_data['maxScore'],
                    "status": q_data['status'],
                    "topic": topics_ai.get(q_data['label'], "Chưa phân loại")
                })

            student_name = data['submission'].student_name or f"HS{s_id}"
            # Tag which AI error patterns this student is affected by
            student_error_tags = []
            for err in errors_ai:
                if student_name in err.get('_resolved_affected_students', []):
                    student_error_tags.append(err.get('tag', ''))

            students_list.append({
                "id": str(s_id),
                "name": student_name,
                "score": data['total_score'],
                "riskScore": data['riskScore'],
                "progress": 0,
                "group": data['group'],
                "studentId": f"HS{s_id}",
                "averageScore": data['total_score'],
                "scoreHistory": [{"test": "Current", "score": data['total_score']}],
                "riskBreakdown": data['riskBreakdown'],
                "questionResults": q_results,
                "progressSteps": [],
                "errors": student_error_tags
            })

        # 2. Build commonErrors (count is now deterministic)
        common_errors = []
        for err in errors_ai:
            affected_list = err.get('_resolved_affected_students', [])
            count = len(affected_list)
            perc = round((count / max(1, class_metrics['totalStudents'])) * 100)
            
            # Use fullDescription if rootCause is missing
            root_cause = err.get('fullDescription') or err.get('rootCause', '')
            
            common_errors.append({
                "id": err.get('id', 'ERR_UNKNOWN'),
                "tag": err.get('tag', 'Lỗi không xác định'),
                "count": count,
                "percentage": perc,
                "severity": err.get('severity', 'medium'),
                "rootCause": root_cause,
                "example": err.get('example', ''),
                "affectedStudents": affected_list,
                "questionIds": err.get('affected_questions', []),
                "recommendation": "\n".join([a.get('description', '') for a in err.get('suggestedActions', [])])
            })
            
        # 3. Build topics
        topics_map = {}
        for q_label, topic_name in topics_ai.items():
            if topic_name not in topics_map:
                topics_map[topic_name] = {"id": f"topic_{len(topics_map)+1}", "name": topic_name, "questions": []}
            topics_map[topic_name]["questions"].append(q_label)
            
        topics_list = []
        for t_name, t_data in topics_map.items():
            # Calculate mastery
            q_labels = t_data['questions']
            correct_count = 0
            total_attempts = 0
            students_with_gaps = []
            
            for s_data in students_list:
                s_correct = []
                s_incorrect = []
                for q_res in s_data['questionResults']:
                    if q_res['question'] in q_labels:
                        total_attempts += 1
                        if q_res['status'] == 'correct':
                            correct_count += 1
                            s_correct.append(q_res['question'])
                        else:
                            s_incorrect.append(q_res['question'])
                
                if s_incorrect:
                    def_perc = round((len(s_incorrect) / max(1, len(q_labels))) * 100)
                    students_with_gaps.append({
                        "id": s_data['id'],
                        "name": s_data['name'],
                        "deficitPercentage": def_perc,
                        "questionsCorrect": s_correct,
                        "questionsIncorrect": s_incorrect,
                        "examples": [f"Sai ở: {', '.join(s_incorrect)}"],
                        "group": s_data['group']
                    })
                    
            t_data["masteryRate"] = round((correct_count / max(1, total_attempts)) * 100)
            t_data["studentsWithGaps"] = students_with_gaps
            topics_list.append(t_data)
            
        # 4. Build errorDetailMap
        error_detail_map = {}
        for err in errors_ai:
            err_id = err.get('id', '')
            if err_id:
                # Use resolved names
                affected_names = err.get('_resolved_affected_students', [])
                aff_students_detailed = []
                for s_name in affected_names:
                    s_match = next((s for s in students_list if s['name'] == s_name), None)
                    if s_match:
                        aff_students_detailed.append({
                            "id": s_match['id'],
                            "name": s_match['name'],
                            "group": s_match['group'],
                            "score": s_match['score'],
                            "errors": err.get('affected_questions', [])
                        })
                
                root_cause = err.get('fullDescription') or err.get('rootCause', '')
                error_detail_map[err_id] = {
                    "fullDescription": root_cause,
                    "commonMistakes": err.get('commonMistakes', []),
                    "affectedStudents": aff_students_detailed,
                    "relatedTopics": err.get('relatedTopics', []),
                    "suggestedActions": err.get('suggestedActions', [])
                }
                
        # 5. Build groupDetailMap
        group_detail_map = {}
        for g_name, g_data in student_groups.items():
            # Get AI interventions
            g_interventions = interventions_ai.get(g_name, {"immediate": [], "longTerm": []})
            
            # Map weaknesses to the exact string required by dashboard
            g_weaknesses = []
            for w in group_weaknesses.get(g_name, []):
                 g_weaknesses.append({
                     "topic": w['question_label'] + " - " + topics_ai.get(w['question_label'], ""),
                     "percentage": w['percentage'],
                     "description": w['description']
                 })
                 
            # Find common errors for this group
            g_errors = []
            for err in common_errors:
                # Count how many students in this group have this error
                g_err_count = sum(1 for s_name in err['affectedStudents'] if any(s['name'] == s_name for s in g_data['students']))
                if g_err_count > 0:
                    g_errors.append({
                        "error": f"{err['id']} - {err['tag']}",
                        "count": g_err_count,
                        "severity": err['severity']
                    })

            # Also store just the string values for the high-level studentGroups array
            g_error_strings = [e['tag'] for e in common_errors if any(s['name'] in e['affectedStudents'] for s in g_data['students'])]
            g_weakness_strings = [w['question_label'] for w in group_weaknesses.get(g_name, [])]

            group_detail_map[g_name] = {
                "name": g_data['name'],
                "count": g_data['count'],
                "averageScore": g_data['averageScore'],
                "riskLevel": g_data['riskLevel'],
                "students": [{"id": s['id'], "name": s['name'], "score": s['score'], "riskScore": s['riskScore'], "group": s['group']} for s in g_data['students']],
                "commonWeaknesses": g_weaknesses,
                "commonErrors": g_errors,
                "interventionPlan": g_interventions
            }
            
        # 6. Format studentGroups array for dashboard
        student_groups_list = []
        for g_name, g_data in student_groups.items():
             g_details = group_detail_map.get(g_name, {})
             # Sort string arrays by occurrence or relevance
             g_error_strings = [e['error'].split(' - ', 1)[-1] for e in sorted(g_details.get('commonErrors', []), key=lambda x: x['count'], reverse=True)[:3]]
             g_weakness_strings = [w['topic'] for w in g_details.get('commonWeaknesses', [])[:3]]
             
             student_groups_list.append({
                 "id": g_data['id'],
                 "name": g_data['name'],
                 "level": g_data['level'],
                 "count": g_data['count'],
                 "percentage": g_data.get('percentage', 0),
                 "averageScore": g_data.get('averageScore', 0),
                 "commonErrors": g_error_strings,
                 "knowledgeGaps": g_weakness_strings,
                 "riskLevel": "low" if g_name in ["Giỏi", "Khá"] else ("medium" if g_name == "TB" else "high")
             })

        # 7. Build aiInsights — merge AI-generated narrative with deterministic student data
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()

        raw_ai_insights = ai_response.get("ai_insights", {})

        # Find lowest-scoring student from the already-built students_list
        lowest_student = None
        if students_list:
            lowest_student = min(students_list, key=lambda s: s["score"])

        urgent_action_ai = raw_ai_insights.get("urgentAction", {})
        overview_insight = raw_ai_insights.get("overviewInsight", "")

        # Build urgentAction with deterministic student info merged with AI text
        urgent_action = None
        if lowest_student:
            urgent_action = {
                "studentName": lowest_student["name"],
                "studentScore": lowest_student["score"],
                "title": urgent_action_ai.get("title", f"Hỗ trợ khẩn cấp — {lowest_student['name']}"),
                "description": urgent_action_ai.get("description", f"Học sinh {lowest_student['name']} đạt {lowest_student['score']}/10, cần được can thiệp ngay."),
                "triggerRule": "at_risk_student"
            }

        # Build suggestedActions — 2 AI-template messages enriched with metadata
        raw_suggested = raw_ai_insights.get("suggestedActions", [{}, {}])
        class_action_raw = raw_suggested[0] if len(raw_suggested) > 0 else {}
        student_action_raw = raw_suggested[1] if len(raw_suggested) > 1 else {}

        # Most common error for class-level action fallback
        top_error_tag = common_errors[0]["tag"] if common_errors else "lỗi phổ biến"

        suggested_actions = [
            {
                "id": f"ai_class_{int(datetime.now(timezone.utc).timestamp())}",
                "type": "class",
                "subject": class_action_raw.get("subject", f"Lưu ý lỗi phổ biến: {top_error_tag}"),
                "content": class_action_raw.get("content", f"Kính gửi cả lớp, qua bài kiểm tra vừa rồi, nhiều bạn đang gặp khó khăn với lỗi '{top_error_tag}'. Các bạn hãy xem lại và thực hành thêm nhé."),
                "recipients": ["all"],
                "recipientNames": ["Toàn lớp"],
                "sentAt": now_iso,
                "status": "suggested",
                "canRevoke": False
            }
        ]

        if lowest_student:
            suggested_actions.append({
                "id": f"ai_student_{lowest_student['id']}_{int(datetime.now(timezone.utc).timestamp())}",
                "type": "individual",
                "subject": student_action_raw.get("subject", f"Hỗ trợ riêng — {lowest_student['name']}"),
                "content": student_action_raw.get("content", urgent_action["description"] if urgent_action else f"Em {lowest_student['name']} cần được hỗ trợ thêm sau bài kiểm tra."),
                "recipients": [str(lowest_student["id"])],
                "recipientNames": [lowest_student["name"]],
                "sentAt": now_iso,
                "status": "suggested",
                "canRevoke": False
            })

        ai_insights = {
            "overviewInsight": overview_insight,
            "urgentAction": urgent_action,
            "suggestedActions": suggested_actions
        }

        return {
            "classMetrics": class_metrics,
            "students": students_list,
            "commonErrors": common_errors,
            "studentGroups": student_groups_list,
            "topics": topics_list,
            "errorDetailMap": error_detail_map,
            "groupDetailMap": group_detail_map,
            "aiInsights": ai_insights
        }
