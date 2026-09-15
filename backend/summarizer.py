"""
Summarization Module for Audio-Notes

Provides a configurable interface for generating structured lecture summaries
from transcripts, with a reliable local fallback implementation.

Provider Configuration:
    Set via environment variable AUDIO_NOTES_SUMMARIZER:
    - "local" (default): Extractive/rule-based local summarizer
    - Future providers: "openai", "anthropic", "custom"

Architecture:
    - Summarizer protocol defines the interface
    - LocalFallbackSummarizer implements extractive summarization
    - SummarizerFactory creates appropriate provider
    - Extension point for cloud LLM providers (not yet implemented)
"""

from typing import Protocol, Optional
import re
import os
import logging
from collections import Counter

logger = logging.getLogger("summarizer")

# ===== Summarizer Protocol =====

class Summarizer(Protocol):
    """Protocol defining the summarizer interface."""

    def summarize(self, transcript: str, title: Optional[str] = None) -> str:
        """
        Generate a structured Markdown summary from a transcript.

        Args:
            transcript: Full lecture transcript text
            title: Optional lecture title for context

        Returns:
            Structured Markdown summary

        Raises:
            ValueError: If transcript is invalid
            Exception: For provider-specific errors
        """
        ...


# ===== Local Fallback Summarizer =====

class LocalFallbackSummarizer:
    """
    Local extractive summarizer that creates structured notes without LLM calls.

    This is a deterministic rule-based implementation that:
    - Extracts key sentences using heuristics
    - Identifies definitions and formulas
    - Detects questions and action items
    - Handles long transcripts with bounded processing

    Limitations:
    - No semantic understanding or reasoning
    - Cannot paraphrase or synthesize information
    - May miss context-dependent insights
    - Optimized for lectures, tutorials, and presentations

    Recommended upgrade: Replace with Claude API or OpenAI for better summaries.
    """

    MAX_CHUNK_SIZE = 5000  # chars per processing chunk
    MAX_SENTENCES_PER_SECTION = 10

    def summarize(self, transcript: str, title: Optional[str] = None) -> str:
        """Generate structured Markdown summary from transcript."""

        if not transcript or not transcript.strip():
            return self._empty_summary()

        # Normalize whitespace and clean transcript
        cleaned = self._clean_transcript(transcript)

        # Split into sentences
        sentences = self._split_sentences(cleaned)

        if not sentences:
            return self._empty_summary()

        # Remove near-duplicate sentences
        unique_sentences = self._deduplicate_sentences(sentences)

        # Extract different types of content
        definitions = self._extract_definitions(unique_sentences)
        formulas = self._extract_formulas(unique_sentences)
        questions = self._extract_questions(unique_sentences)
        key_sentences = self._extract_key_sentences(unique_sentences)

        # Build structured summary
        return self._build_markdown_summary(
            title=title,
            key_sentences=key_sentences,
            definitions=definitions,
            formulas=formulas,
            questions=questions,
            total_sentences=len(unique_sentences)
        )

    def _clean_transcript(self, text: str) -> str:
        """Normalize whitespace and clean transcript."""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove common filler patterns
        text = re.sub(r'\b(um|uh|like|you know)\b', '', text, flags=re.IGNORECASE)
        return text.strip()

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences using simple heuristics."""
        # Split on sentence boundaries
        sentences = re.split(r'[.!?]+\s+', text)
        # Filter out very short fragments
        return [s.strip() for s in sentences if len(s.strip()) > 10]

    def _deduplicate_sentences(self, sentences: list[str]) -> list[str]:
        """Remove near-duplicate sentences using normalized comparison."""
        seen = set()
        unique = []

        for sent in sentences:
            # Normalize for comparison
            normalized = re.sub(r'\W+', '', sent.lower())
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(sent)

        return unique

    def _extract_definitions(self, sentences: list[str]) -> list[str]:
        """Extract sentences that look like definitions."""
        definition_patterns = [
            r'\b(?:is|are|means|refers to|defined as)\b',
            r'\b(?:definition|terminology|term)\b',
            r'^[A-Z][a-z]+\s+(?:is|are)\s+',
        ]

        definitions = []
        for sent in sentences:
            for pattern in definition_patterns:
                if re.search(pattern, sent, re.IGNORECASE):
                    definitions.append(sent)
                    break

        return definitions[:self.MAX_SENTENCES_PER_SECTION]

    def _extract_formulas(self, sentences: list[str]) -> list[str]:
        """Extract sentences that contain mathematical or formula-like content."""
        formula_indicators = [
            r'\b(?:formula|equation|calculate|compute)\b',
            r'[=×÷+\-]',
            r'\d+\s*[+\-×÷]\s*\d+',
            r'\b(?:equals|plus|minus|times|divided by)\b',
        ]

        formulas = []
        for sent in sentences:
            for pattern in formula_indicators:
                if re.search(pattern, sent, re.IGNORECASE):
                    formulas.append(sent)
                    break

        return formulas[:self.MAX_SENTENCES_PER_SECTION]

    def _extract_questions(self, sentences: list[str]) -> list[str]:
        """Extract questions and action items."""
        questions = []

        for sent in sentences:
            # Direct questions
            if '?' in sent:
                questions.append(sent)
            # Action items
            elif re.search(r'\b(?:should|must|need to|have to|remember to)\b', sent, re.IGNORECASE):
                questions.append(sent)
            # Imperatives
            elif re.search(r'^(?:Note|Remember|Consider|Think about|Don\'t forget)', sent):
                questions.append(sent)

        return questions[:self.MAX_SENTENCES_PER_SECTION]

    def _extract_key_sentences(self, sentences: list[str]) -> list[str]:
        """Extract key sentences using importance heuristics."""
        scored_sentences = []

        # Importance indicators
        importance_keywords = [
            'important', 'key', 'critical', 'essential', 'main', 'primary',
            'fundamental', 'significant', 'crucial', 'note', 'remember'
        ]

        structural_keywords = [
            'first', 'second', 'finally', 'in conclusion', 'to summarize',
            'therefore', 'however', 'additionally', 'furthermore'
        ]

        for sent in sentences:
            score = 0
            sent_lower = sent.lower()

            # Check for importance keywords
            for kw in importance_keywords:
                if kw in sent_lower:
                    score += 2

            # Check for structural keywords
            for kw in structural_keywords:
                if kw in sent_lower:
                    score += 1

            # Prefer sentences with proper nouns (likely topics)
            if re.search(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', sent):
                score += 1

            # Prefer moderate-length sentences
            word_count = len(sent.split())
            if 8 <= word_count <= 30:
                score += 1

            scored_sentences.append((score, sent))

        # Sort by score and take top sentences
        scored_sentences.sort(reverse=True, key=lambda x: x[0])
        return [sent for score, sent in scored_sentences[:self.MAX_SENTENCES_PER_SECTION]]

    def _build_markdown_summary(
        self,
        title: Optional[str],
        key_sentences: list[str],
        definitions: list[str],
        formulas: list[str],
        questions: list[str],
        total_sentences: int
    ) -> str:
        """Build the final structured Markdown summary."""

        lines = ["# Lecture Notes\n"]

        if title:
            lines.append(f"**Title:** {title}\n")

        lines.append(f"**Source:** Extracted from {total_sentences} unique sentences\n")

        # Overview
        lines.append("## Overview\n")
        if key_sentences:
            for sent in key_sentences[:5]:
                lines.append(f"- {sent}\n")
        else:
            lines.append("- No key overview points automatically extracted\n")

        # Key Concepts
        lines.append("\n## Key Concepts\n")
        if key_sentences:
            for sent in key_sentences[5:10] if len(key_sentences) > 5 else key_sentences:
                lines.append(f"- {sent}\n")
        else:
            lines.append("- No explicit key concepts identified\n")

        # Important Details (using remaining key sentences)
        lines.append("\n## Important Details\n")
        remaining_sentences = key_sentences[10:] if len(key_sentences) > 10 else []
        if remaining_sentences:
            for sent in remaining_sentences[:5]:
                lines.append(f"- {sent}\n")
        else:
            lines.append("- No additional details extracted\n")

        # Definitions and Formulas
        lines.append("\n## Definitions and Formulas\n")
        has_content = False

        if definitions:
            lines.append("\n**Definitions:**\n")
            for defn in definitions[:5]:
                lines.append(f"- {defn}\n")
            has_content = True

        if formulas:
            lines.append("\n**Formulas and Calculations:**\n")
            for formula in formulas[:5]:
                lines.append(f"- {formula}\n")
            has_content = True

        if not has_content:
            lines.append("- No explicit definitions or formulas found\n")

        # Action Items or Follow-up Questions
        lines.append("\n## Action Items or Follow-up Questions\n")
        if questions:
            for q in questions[:5]:
                lines.append(f"- {q}\n")
        else:
            lines.append("- No explicit action items or questions identified\n")

        # Footer note
        lines.append("\n---\n")
        lines.append("*Note: This summary was generated using local extractive methods. ")
        lines.append("For higher-quality summaries with semantic understanding, ")
        lines.append("configure a cloud LLM provider (OpenAI, Anthropic Claude).*\n")

        return "".join(lines)

    def _empty_summary(self) -> str:
        """Return a summary for empty/invalid transcripts."""
        return """# Lecture Notes

## Overview
- No transcript content available to summarize

## Key Concepts
- Transcript was empty or contained no extractable content

## Important Details
- No details available

## Definitions and Formulas
- No definitions or formulas found

## Action Items or Follow-up Questions
- No action items identified

---
*Note: The transcript was empty or too short to generate a meaningful summary.*
"""


# ===== Cloud Provider Placeholder =====

# Future implementation example:
#
# class AnthropicSummarizer:
#     """Claude-based summarizer using Anthropic API."""
#
#     def __init__(self, api_key: str):
#         self.api_key = api_key
#
#     def summarize(self, transcript: str, title: Optional[str] = None) -> str:
#         # Implementation would:
#         # 1. Check transcript length
#         # 2. Split into chunks if needed (map-reduce)
#         # 3. Call Claude API with structured prompt
#         # 4. Return formatted Markdown
#         pass
#
# class OpenAISummarizer:
#     """GPT-based summarizer using OpenAI API."""
#
#     def __init__(self, api_key: str):
#         self.api_key = api_key
#
#     def summarize(self, transcript: str, title: Optional[str] = None) -> str:
#         # Implementation would use ChatGPT with structured output
#         pass


# ===== Summarizer Factory =====

def create_summarizer(provider: Optional[str] = None) -> Summarizer:
    """
    Create a summarizer instance based on configuration.

    Args:
        provider: Summarizer provider name. If None, reads from
                 AUDIO_NOTES_SUMMARIZER environment variable.

    Returns:
        Configured summarizer instance
    """

    if provider is None:
        provider = os.environ.get("AUDIO_NOTES_SUMMARIZER", "local")

    provider = provider.lower().strip()

    logger.info(f"Creating summarizer: provider={provider}")

    if provider == "local":
        return LocalFallbackSummarizer()

    # Future providers
    elif provider == "anthropic":
        logger.warning("Anthropic provider not yet implemented, falling back to local")
        return LocalFallbackSummarizer()

    elif provider == "openai":
        logger.warning("OpenAI provider not yet implemented, falling back to local")
        return LocalFallbackSummarizer()

    else:
        logger.warning(f"Unknown provider '{provider}', falling back to local")
        return LocalFallbackSummarizer()


# ===== Convenience Function =====

def summarize_transcript(transcript: str, title: Optional[str] = None, provider: Optional[str] = None) -> str:
    """
    Convenience function to summarize a transcript.

    Args:
        transcript: Full lecture transcript
        title: Optional lecture title
        provider: Optional provider override

    Returns:
        Structured Markdown summary
    """
    summarizer = create_summarizer(provider)
    return summarizer.summarize(transcript, title)
