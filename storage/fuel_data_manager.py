# Add fuel measurements, AI reports and review decisions to the existing DataManager.
from __future__ import annotations

import os

from data_manager import DataManager
from storage.fuel_repository import FuelRepository
from storage.fuel_assessment_repository import FuelAssessmentRepository
from storage.fuel_review_repository import FuelReviewRepository
from storage.repository_factory import RepositoryFactory


class FuelDataManager(DataManager):
    FUEL_FILENAME = "fuel_history.json"
    FUEL_ASSESSMENT_FILENAME = "fuel_assessments.json"
    FUEL_REVIEW_FILENAME = "fuel_reviews.json"

    # Start the existing DataManager first, then add fuel storage.
    def __init__(self, data_dir: str | None = None, project_dir: str | None = None,
                 repositories: RepositoryFactory | None = None):
        super().__init__(data_dir=data_dir, project_dir=project_dir, repositories=repositories)
        # The parent's factory decides whether these are JSON files or MongoDB collections.
        create = self._repositories.create
        self.__fuel = FuelRepository(
            create(os.path.join(self.data_dir, self.FUEL_FILENAME)))
        self.__fuel_assessments = FuelAssessmentRepository(
            create(os.path.join(self.data_dir, self.FUEL_ASSESSMENT_FILENAME)))
        self.__fuel_reviews = FuelReviewRepository(
            create(os.path.join(self.data_dir, self.FUEL_REVIEW_FILENAME)))

    # Return the fuel repository to the controller.
    @property
    def fuel(self) -> FuelRepository:
        return self.__fuel

    # Keep AI reports in their own JSON file.
    @property
    def fuel_assessments(self) -> FuelAssessmentRepository:
        return self.__fuel_assessments

    # Reviews survive restarts and never overwrite the original fuel measurements.
    @property
    def fuel_reviews(self) -> FuelReviewRepository:
        return self.__fuel_reviews
