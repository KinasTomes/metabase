(ns metabase.metabot.self.core-test
  (:require
   [clojure.test :refer :all]
   [metabase.metabot.self.core :as self.core]))

(set! *warn-on-reflection* true)

(deftest aisdk-xf-consolidates-grouped-tool-input-test
  (testing "start + deltas sharing a toolCallId consolidate into one :tool-input part"
    (is (=? [{:type      :tool-input
              :id        "t1"
              :function  "search"
              :arguments {:query "gsm"}}]
            (into []
                  (self.core/aisdk-xf)
                  [{:type :tool-input-start :toolCallId "t1" :toolName "search"}
                   {:type :tool-input-delta :toolCallId "t1" :inputTextDelta "{\"query\":"}
                   {:type :tool-input-delta :toolCallId "t1" :inputTextDelta "\"gsm\"}"}])))))

(deftest aisdk-xf-keeps-parallel-tool-calls-apart-test
  (testing "two tool calls with distinct ids produce two parts with their own arguments"
    (let [parts (into []
                      (self.core/aisdk-xf)
                      [{:type :tool-input-start :toolCallId "a" :toolName "search"}
                       {:type :tool-input-delta :toolCallId "a" :inputTextDelta "{\"q\":\"gsm\"}"}
                       {:type :tool-input-available :toolCallId "a" :toolName "search"}
                       {:type :tool-input-start :toolCallId "b" :toolName "read_resource"}
                       {:type :tool-input-delta :toolCallId "b" :inputTextDelta "{\"uri\":\"metabase://table/42/fields\"}"}
                       {:type :tool-input-available :toolCallId "b" :toolName "read_resource"}])]
      (is (= ["a" "b"] (mapv :id parts)))
      (is (= ["search" "read_resource"] (mapv :function parts)))
      (is (= [{:q "gsm"} {:uri "metabase://table/42/fields"}] (mapv :arguments parts))))))

(deftest aisdk-xf-tolerates-ungrouped-tool-input-available-test
  (testing "a group that starts at :tool-input-available consolidates instead of throwing
           — parallel calls splitting across flush boundaries used to kill the agent
           loop with 'No matching clause: :tool-input-available' (observed live on Q15)"
    (is (=? [{:type      :tool-input
              :id        "x"
              :function  "read_resource"
              :arguments {:_raw_arguments ""}}]
            (into []
                  (self.core/aisdk-xf)
                  [{:type :tool-input-available :toolCallId "x" :toolName "read_resource"}]))))
  (testing "an available chunk arriving after its group was flushed also degrades gracefully"
    (is (=? [{:type :tool-input :id "a" :function "search"}
             {:type :tool-input :id "b" :function "analyze_chart"}]
            (into []
                  (self.core/aisdk-xf)
                  [{:type :tool-input-start :toolCallId "a" :toolName "search"}
                   ;; the id change flushes a's group before b's available lands
                   {:type :tool-input-available :toolCallId "b" :toolName "analyze_chart"}])))))
